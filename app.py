from flask import Flask, request, jsonify
import os
import json
import hashlib
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from github import Github, Auth
import threading

# Load environment variables (only for local development)
if os.path.exists('.env'):
    load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
SECRET = os.getenv('SECRET')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')

# Initialize clients
genai.configure(api_key=GEMINI_API_KEY)
auth = Auth.Token(GITHUB_TOKEN)
github_client = Github(auth=auth)

# Track processed tasks to prevent duplicates
processed_tasks = {}

def verify_secret(provided_secret):
    """Verify the secret matches"""
    return provided_secret == SECRET

def generate_code_with_llm(brief, checks, attachments):
    """Generate HTML/JS code using Gemini"""
    print("Generating code with LLM...")
    
    prompt = f"""Create a complete, working HTML file for this task:

Task: {brief}

Requirements:
{chr(10).join(f"- {check}" for check in checks)}

Rules:
1. Create a SINGLE HTML file with embedded CSS and JavaScript
2. Use CDN links for any libraries (Bootstrap, etc.)
3. Make it functional and complete
4. Include proper error handling
5. Style it nicely with Bootstrap 5
6. Add responsive design

Additional data/files:
{json.dumps(attachments) if attachments else "None"}

Return ONLY the HTML code, no explanations."""

    model = genai.GenerativeModel('gemini-pro')
    response = model.generate_content(prompt)
    
    code = response.text.strip()
    
    # Clean up markdown code blocks if present
    if code.startswith('```html'):
        code = code.split('```html')[1].split('```')[0].strip()
    elif code.startswith('```'):
        code = code.split('```')[1].split('```')[0].strip()
    
    return code

def create_github_repo(repo_name, html_code, brief):
    """Create GitHub repository and push code"""
    print(f"Creating GitHub repository: {repo_name}")
    
    try:
        user = github_client.get_user()
        
        # Check if repo already exists
        try:
            existing_repo = user.get_repo(repo_name)
            print(f"Repository {repo_name} already exists, using existing one")
            repo = existing_repo
        except:
            # Create new repository
            repo = user.create_repo(
                name=repo_name,
                description=f"Auto-generated app: {brief}",
                private=False,
                auto_init=False
            )
            print(f"Repository created: {repo.html_url}")
        
        # Create LICENSE file
        license_content = """MIT License

Copyright (c) 2024

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""
        
        # Create README
        readme_content = f"""# {repo_name}

## Description
{brief}

## Features
Auto-generated application using LLM-assisted deployment system.

## Usage
Visit the live site: https://{GITHUB_USERNAME}.github.io/{repo_name}/

## License
MIT License - see LICENSE file for details.

## Auto-generated
This repository was automatically generated and deployed.
"""
        
        # Push files to repo
        try:
            # Try to get existing files first
            try:
                repo.get_contents("index.html")
                # Update existing files
                repo.update_file("index.html", "Update app", html_code, repo.get_contents("index.html").sha)
                repo.update_file("README.md", "Update README", readme_content, repo.get_contents("README.md").sha)
                repo.update_file("LICENSE", "Update LICENSE", license_content, repo.get_contents("LICENSE").sha)
            except:
                # Create new files
                repo.create_file("index.html", "Initial commit: Add app", html_code)
                repo.create_file("README.md", "Initial commit: Add README", readme_content)
                repo.create_file("LICENSE", "Initial commit: Add LICENSE", license_content)
            
            print("Files pushed successfully")
        except Exception as e:
            print(f"Error pushing files: {e}")
        
        # Enable GitHub Pages
        try:
            repo.create_pages_site(source={"branch": "main", "path": "/"})
            print("GitHub Pages enabled")
        except Exception as e:
            # Pages might already be enabled
            print(f"Pages setup: {e}")
        
        # Wait a bit for Pages to deploy
        time.sleep(10)
        
        return {
            'repo_url': repo.html_url,
            'pages_url': f"https://{GITHUB_USERNAME}.github.io/{repo_name}/",
            'commit_sha': repo.get_commits()[0].sha
        }
        
    except Exception as e:
        print(f"Error creating repository: {e}")
        raise Exception(f"Repository creation failed: {str(e)}")

def submit_to_evaluation(evaluation_url, task_id, nonce, repo_data):
    """Submit results to evaluation API with retry logic"""
    print(f"Submitting to evaluation URL: {evaluation_url}")
    
    payload = {
        'task': task_id,
        'nonce': nonce,
        'repo_url': repo_data['repo_url'],
        'pages_url': repo_data['pages_url'],
        'commit_sha': repo_data['commit_sha']
    }
    
    # Retry logic with exponential backoff
    for attempt in range(4):
        try:
            wait_time = 2 ** attempt  # 1, 2, 4, 8 seconds
            if attempt > 0:
                print(f"Retry attempt {attempt + 1} after {wait_time}s")
                time.sleep(wait_time)
            
            response = requests.post(evaluation_url, json=payload, timeout=30)
            
            if response.status_code == 200:
                print("Successfully submitted to evaluation API")
                return True
            else:
                print(f"Evaluation API returned {response.status_code}: {response.text}")
                
        except Exception as e:
            print(f"Error submitting to evaluation API: {e}")
            if attempt == 3:  # Last attempt
                return False
    
    return False

def process_task_background(task_data):
    """Process the task in background thread"""
    try:
        task_id = task_data['task']
        brief = task_data['brief']
        checks = task_data['checks']
        attachments = task_data.get('attachments', [])
        evaluation_url = task_data['evaluation_url']
        nonce = task_data['nonce']
        
        print(f"Background processing started for task: {task_id}")
        
        # Generate code
        html_code = generate_code_with_llm(brief, checks, attachments)
        
        # Create GitHub repo and deploy
        repo_data = create_github_repo(task_id, html_code, brief)
        
        # Submit to evaluation
        submit_to_evaluation(evaluation_url, task_id, nonce, repo_data)
        
        # Mark as processed
        processed_tasks[task_id] = {
            'status': 'completed',
            'repo_url': repo_data['repo_url'],
            'pages_url': repo_data['pages_url']
        }
        
        print(f"Task {task_id} completed successfully!")
        
    except Exception as e:
        print(f"Error processing task {task_id}: {e}")
        processed_tasks[task_id] = {
            'status': 'failed',
            'error': str(e)
        }

@app.route('/api/deploy', methods=['POST'])
def deploy():
    """Main endpoint to receive deployment requests"""
    try:
        data = request.get_json()
        
        # Extract required fields
        email = data.get('email')
        secret = data.get('secret')
        task_id = data.get('task')
        round_num = data.get('round', 1)
        nonce = data.get('nonce')
        brief = data.get('brief')
        checks = data.get('checks', [])
        attachments = data.get('attachments', [])
        evaluation_url = data.get('evaluation_url')
        
        print(f"\n{'='*60}")
        print(f"Received request for task: {task_id} (Round {round_num})")
        print(f"Brief: {brief}")
        print(f"{'='*60}\n")
        
        # Verify secret
        if not verify_secret(secret):
            print("Secret verification failed!")
            return jsonify({'error': 'Invalid secret'}), 401
        
        print("Secret verified ✓")
        
        # Check if already processing/processed
        if task_id in processed_tasks:
            status = processed_tasks[task_id]
            if status['status'] == 'completed':
                return jsonify({
                    'status': 'success',
                    'message': 'Task already completed',
                    'repo_url': status['repo_url'],
                    'pages_url': status['pages_url']
                }), 200
            elif status['status'] == 'processing':
                return jsonify({
                    'status': 'processing',
                    'message': 'Task is being processed'
                }), 200
        
        # Mark as processing
        processed_tasks[task_id] = {'status': 'processing'}
        
        # Start background processing
        thread = threading.Thread(
            target=process_task_background,
            args=(data,)
        )
        thread.daemon = True
        thread.start()
        
        # Return immediate success response
        return jsonify({
            'status': 'success',
            'message': 'Task accepted and is being processed',
            'task': task_id
        }), 200
        
    except Exception as e:
        print(f"Error in deploy endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

@app.route('/', methods=['GET'])
def home():
    """Root endpoint"""
    return jsonify({
        'service': 'LLM Code Deployment API',
        'status': 'running',
        'endpoint': '/api/deploy'
    }), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)