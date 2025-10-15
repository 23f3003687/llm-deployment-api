from flask import Flask, request, jsonify
import os
import json
import hashlib
import time
import requests
from dotenv import load_dotenv
import google.generativeai as genai
from github import Github, Auth


# Load environment variables (only for local development)
if os.path.exists('.env'):
    load_dotenv()

app = Flask(__name__)

# Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
SECRET = os.getenv('SECRET')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME')

# Initialize APIs
genai.configure(api_key=GEMINI_API_KEY)

auth = Auth.Token(GITHUB_TOKEN)
github_client = Github(auth=auth)

def verify_secret(request_data):
    """Verify the secret from the request"""
    return request_data.get('secret') == SECRET

def generate_code_with_llm(brief, checks, attachments):
    """Use Gemini to generate HTML/JS code based on brief"""
    
    # Prepare prompt for LLM
    prompt = f"""You are an expert web developer. Create a single-page HTML application based on this brief:

BRIEF: {brief}

REQUIREMENTS (These will be tested):
{chr(10).join(f"- {check}" for check in checks)}

ATTACHMENTS:
{json.dumps(attachments, indent=2)}

Generate a complete, working HTML file that:
1. Includes all necessary CSS (inline or in <style> tags)
2. Includes all necessary JavaScript (inline or in <script> tags)
3. Uses CDN links for any external libraries (from cdnjs.cloudflare.com only)
4. Handles the attachments properly (they're provided as data URIs)
5. Is production-ready and fully functional
6. Meets ALL the requirements listed above

Return ONLY the complete HTML code, no explanations, no markdown formatting, just the raw HTML."""

    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(prompt)
        code = response.text
        
        # Remove markdown code blocks if present
        if '```html' in code:
            code = code.split('```html')[1].split('```')[0].strip()
        elif '```' in code:
            code = code.split('```')[1].split('```')[0].strip()
        
        return code
    except Exception as e:
        print(f"Error generating code: {e}")
        # Return a basic template if LLM fails
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Generated App</title>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <div class="container mt-5">
        <h1>Application</h1>
        <p>{brief}</p>
    </div>
</body>
</html>"""

def generate_readme(brief, task_id, repo_name):
    """Generate a professional README.md"""
    return f"""# {repo_name}

## Summary
This application was automatically generated to fulfill the following requirement:

{brief}

## Setup
1. Clone this repository
2. Open `index.html` in a web browser or deploy to any static hosting service

## Usage
Simply open the deployed GitHub Pages URL or run locally by opening `index.html`.

## Code Explanation
This is a single-page web application that:
- Uses modern HTML5, CSS3, and JavaScript
- Implements the required functionality as specified
- Uses CDN-hosted libraries for dependencies
- Is fully self-contained and ready for deployment

## Technologies Used
- HTML5
- CSS3 (Bootstrap 5 for styling)
- Vanilla JavaScript
- External libraries loaded from CDN

## License
MIT License - See LICENSE file for details

## Task Information
- Task ID: {task_id}
- Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
"""

def create_github_repo(task_id, html_code, brief):
    """Create GitHub repository and push code"""
    try:
        user = github_client.get_user()
        
        # Create unique repo name
        repo_name = f"{task_id}"
        
        # Create repository
        repo = user.create_repo(
            repo_name,
            description=f"Auto-generated app: {brief[:100]}",
            private=False,
            auto_init=False
        )
        
        # Create and push index.html
        repo.create_file(
            "index.html",
            "Initial commit: Add index.html",
            html_code
        )
        
        # Create and push LICENSE
        mit_license = """MIT License

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
        
        repo.create_file(
            "LICENSE",
            "Add MIT LICENSE",
            mit_license
        )
        
        # Create and push README.md
        readme_content = generate_readme(brief, task_id, repo_name)
        repo.create_file(
            "README.md",
            "Add README",
            readme_content
        )
        
        # Enable GitHub Pages
        try:
            repo.create_pages_site(branch="main")
        except:
            # Pages might already be enabled or need time
            pass
        
        # Get URLs
        repo_url = repo.html_url
        commit_sha = repo.get_commits()[0].sha
        pages_url = f"https://{GITHUB_USERNAME}.github.io/{repo_name}/"
        
        return {
            'repo_url': repo_url,
            'commit_sha': commit_sha,
            'pages_url': pages_url
        }
        
    except Exception as e:
        print(f"Error creating repo: {e}")
        raise

def send_to_evaluation(evaluation_url, data, max_retries=5):
    """Send data to evaluation URL with exponential backoff"""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                evaluation_url,
                json=data,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            
            if response.status_code == 200:
                print(f"Successfully sent to evaluation URL")
                return True
            else:
                print(f"Evaluation URL returned status {response.status_code}")
                
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
        
        if attempt < max_retries - 1:
            wait_time = 2 ** attempt  # 1, 2, 4, 8 seconds
            print(f"Retrying in {wait_time} seconds...")
            time.sleep(wait_time)
    
    return False

@app.route('/api/deploy', methods=['POST'])
def deploy():
    """Main endpoint to receive tasks and deploy apps"""
    try:
        data = request.json
        
        # Verify secret
        if not verify_secret(data):
            return jsonify({'error': 'Invalid secret'}), 401
        
        # Extract data
        email = data.get('email')
        task = data.get('task')
        round_num = data.get('round')
        nonce = data.get('nonce')
        brief = data.get('brief')
        checks = data.get('checks', [])
        attachments = data.get('attachments', [])
        evaluation_url = data.get('evaluation_url')
        
        print(f"Received task: {task}, round: {round_num}")
        
        # Generate code using LLM
        print("Generating code with LLM...")
        html_code = generate_code_with_llm(brief, checks, attachments)
        
        # Create GitHub repo and deploy
        print("Creating GitHub repository...")
        repo_info = create_github_repo(task, html_code, brief)
        
        # Wait a bit for Pages to deploy
        print("Waiting for GitHub Pages to deploy...")
        time.sleep(30)
        
        # Prepare evaluation response
        eval_data = {
            'email': email,
            'task': task,
            'round': round_num,
            'nonce': nonce,
            'repo_url': repo_info['repo_url'],
            'commit_sha': repo_info['commit_sha'],
            'pages_url': repo_info['pages_url']
        }
        
        # Send to evaluation URL
        print("Sending to evaluation URL...")
        send_to_evaluation(evaluation_url, eval_data)
        
        return jsonify({
            'status': 'success',
            'message': 'App deployed successfully',
            'repo_url': repo_info['repo_url'],
            'pages_url': repo_info['pages_url']
        }), 200
        
    except Exception as e:
        print(f"Error in deploy endpoint: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)