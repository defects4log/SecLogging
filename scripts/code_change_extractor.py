
import os
import re
import csv
import json
import argparse
import requests
import time
import base64
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
import sys
from datetime import datetime

class CodeChangeExtractor:
    def __init__(self, github_token=None, jira_base_url="https://issues.apache.org/jira"):
        
        self.github_token = github_token
        self.jira_base_url = jira_base_url
        self.github_headers = {}
        
        if github_token:
            self.github_headers = {'Authorization': f'token {github_token}'}
      
        os.makedirs('log_security/data/code_changes', exist_ok=True)
        os.makedirs('log_security/results', exist_ok=True)
        
       
        self.remaining_rate_limit = 5000  
        self.rate_limit_reset_time = 0
        self.check_github_rate_limit()
    
    def check_github_rate_limit(self):
        
        if not self.github_token:
         
            print("Warning: No GitHub token provided. Rate limits will be very restrictive.")
            return True
            
        try:
            response = requests.get('https://api.github.com/rate_limit', headers=self.github_headers)
            if response.status_code == 200:
                data = response.json()
                self.remaining_rate_limit = data['rate']['remaining']
                self.rate_limit_reset_time = data['rate']['reset']
                
                print(f"GitHub API rate limit: {self.remaining_rate_limit} remaining, resets at {datetime.fromtimestamp(self.rate_limit_reset_time)}")
                
                if self.remaining_rate_limit < 10:
                    wait_time = self.rate_limit_reset_time - time.time()
                    if wait_time > 0:
                        print(f"GitHub API rate limit almost exhausted. Waiting for {wait_time:.1f} seconds...")
                        time.sleep(min(wait_time + 1, 60))  
                        return self.check_github_rate_limit()
                
                return self.remaining_rate_limit > 0
            
        except requests.exceptions.RequestException as e:
            print(f"Error checking GitHub rate limit: {e}")
        
        return True 
    
    def github_api_request(self, url, headers=None):
        
        if not headers and self.github_headers:
            headers = self.github_headers
            
        
        if self.remaining_rate_limit < 5:
            if not self.check_github_rate_limit():
                print("GitHub API rate limit reached. Skipping request.")
                return None
        
        try:
            response = requests.get(url, headers=headers)
            
           
            if 'X-RateLimit-Remaining' in response.headers:
                self.remaining_rate_limit = int(response.headers['X-RateLimit-Remaining'])
            if 'X-RateLimit-Reset' in response.headers:
                self.rate_limit_reset_time = int(response.headers['X-RateLimit-Reset'])
            
            if response.status_code == 403 and 'rate limit exceeded' in response.text:
                print(f"GitHub API rate limit exceeded. Reset at {datetime.fromtimestamp(self.rate_limit_reset_time)}")
                wait_time = self.rate_limit_reset_time - time.time()
                if wait_time > 0 and wait_time < 300:  
                    print(f"Waiting for {wait_time:.1f} seconds...")
                    time.sleep(min(wait_time + 1, 60))  
                    return self.github_api_request(url, headers)
                return None
            
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            print(f"Error making GitHub API request to {url}: {e}")
            return None
    
    def process_csv_file(self, csv_file_path, url_column):
        
        results = []
        
      
        encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']
        
        for encoding in encodings_to_try:
            try:
                with open(csv_file_path, 'r', encoding=encoding) as f:
                    print(f"Trying to read file with {encoding} encoding...")
                    reader = csv.DictReader(f)
                    rows = list(reader) 
                break 
            except UnicodeDecodeError:
                print(f"Failed to decode with {encoding} encoding, trying next...")
                continue
        else:
         
            print("All encodings failed. Using latin-1 as fallback (may result in incorrect characters)")
            with open(csv_file_path, 'r', encoding='latin-1') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
        
      
        for row_idx, row in enumerate(rows, start=1):
            print(f"Processing row {row_idx}...")
            
            if url_column not in row or not row[url_column]:
                results.append({
                    'row_idx': row_idx,
                    'success': False,
                    'error': f'Missing {url_column} value'
                })
                continue
            
            url_value = row[url_column].strip()
            
          
            issue_title = row.get('Issue Title', '')
            issue_url = row.get('Issue URL', '')
            
           
            if '+' in url_value:
                related_results = self.process_related_urls(url_value, row_idx, issue_title, issue_url)
                results.extend(related_results)
            else:
                result = self.process_url(url_value, row_idx, is_related=False, related_group=None, issue_title=issue_title, issue_url=issue_url)
                results.append(result)
            
          
            time.sleep(1)
        
        return results
    
    def process_related_urls(self, related_urls, row_idx, issue_title='', issue_url=''):
        
        url_list = related_urls.split('+')
        results = []
        
        for url in url_list:
            url = url.strip()
            if url:
                result = self.process_url(url, row_idx, is_related=True, related_group=related_urls, issue_title=issue_title, issue_url=issue_url)
                results.append(result)
        
        return results
    
    def process_url(self, url, row_idx, is_related=False, related_group=None, issue_title='', issue_url=''):
        
        print(f"  Processing URL: {url}")
        
        
        additional_info = {
            'issue_title': issue_title,
            'issue_url': issue_url
        }
        
     
        if 'github.com' in url and '/pull/' in url and '/commits/' in url:
        
            return self.process_github_pr_commits(url, row_idx, is_related, related_group, additional_info)
        elif 'github.com' in url and '/pull/' in url:
            
            return self.process_github_pr_commits(url, row_idx, is_related, related_group, additional_info)
        elif 'github.com' in url and '/commit/' in url:
          
            match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)', url)
            if match:
                owner, repo, commit_sha = match.groups()
                diff_data = self.fetch_raw_diff(owner, repo, commit_sha)
                if diff_data and diff_data.get('changes'):
                    print(f"  Successfully extracted changes using raw diff")
                    
                    file_name = f"{owner}_{repo}_commit_{commit_sha[:7]}"
                    before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                    after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                    
               
                    before_changes = {
                        'url': url,
                        'type': 'github_commit',
                        'owner': owner,
                        'repo': repo,
                        'commit_sha': commit_sha,
                        'commit_message': diff_data.get('message', ''),
                        'code_changes': [
                            {
                                'filename': change['filename'],
                                'status': change['status'],
                                'content': change['before_content']
                            }
                            for change in diff_data['changes']
                            if change['before_content']
                        ],
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(before_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(before_changes)
                        f.write(formatted_json)
                    
           
                    after_changes = {
                        'url': url,
                        'type': 'github_commit',
                        'owner': owner,
                        'repo': repo,
                        'commit_sha': commit_sha,
                        'commit_message': diff_data.get('message', ''),
                        'code_changes': [
                            {
                                'filename': change['filename'],
                                'status': change['status'],
                                'content': change['after_content']
                            }
                            for change in diff_data['changes']
                            if change['after_content']
                        ],
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(after_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(after_changes)
                        f.write(formatted_json)
                    
                    return {
                        'row_idx': row_idx,
                        'url': url,
                        'success': True,
                        'is_related': is_related,
                        'related_group': related_group,
                        'before_edit_path': before_edit_path,
                        'after_edit_path': after_edit_path,
                        'issue_title': issue_title,
                        'issue_url': issue_url
                    }
            
          
            web_result = self.process_github_commit_web(url, row_idx, is_related, related_group, additional_info)
            if web_result['success']:
                return web_result
                
            
            return self.process_github_commit(url, row_idx, is_related, related_group, additional_info)
        elif 'github.com' in url and '/blob/' in url:
            
            return self.process_github_blob(url, row_idx, is_related, related_group, additional_info)
        elif 'issues.apache.org/jira/browse/' in url:
            return self.process_jira_issue(url, row_idx, is_related, related_group, additional_info)
        elif 'issues.apache.org/jira/secure/attachment' in url and '.patch' in url:
            return self.process_jira_patch(url, row_idx, is_related, related_group, additional_info)
        elif 'issues.apache.org/jira/secure/attachment' in url:
          
            return self.process_jira_attachment(url, row_idx, is_related, related_group, additional_info)
        else:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Unsupported URL type'
            }
            
    def process_jira_attachment(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
        try:
          
            match = re.search(r'attachment/(\d+)/([^/]+)', url)
            if not match:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Invalid JIRA attachment URL'
                }
            
            attachment_id = match.group(1)
            attachment_filename = match.group(2)
            
        
            response = requests.get(url, headers={'X-Atlassian-Token': 'no-check'})
            if response.status_code != 200:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': f'Failed to fetch attachment: status code {response.status_code}'
                }
                
            content = response.text
            
     
            is_log = '.log' in attachment_filename.lower() or 'log.' in attachment_filename.lower()
            
           
            is_text = True
            try:
               
                content.encode('utf-8')
            except UnicodeError:
                is_text = False
                
            if not is_text:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Attachment is not a text file'
                }
                
         
            code_blocks = []
            
            if is_log:
                
                code_blocks.append(content)
            else:
                
                code_blocks = self._extract_code_blocks_from_text(content)
                
               
                if not code_blocks and self._is_code_file(attachment_filename):
                    code_blocks.append(content)
            
            if not code_blocks:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'No code blocks found in attachment'
                }
                
     
            file_name = f"jira_attachment_{attachment_id}"
            content_path = f'log_security/data/code_changes/{file_name}_content.json'
            
       
            attachment_data = {
                'url': url,
                'type': 'jira_attachment',
                'attachment_id': attachment_id,
                'filename': attachment_filename,
                'code_blocks': code_blocks
            }
            
            with open(content_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(attachment_data)
                f.write(formatted_json)
            
            return {
                'row_idx': row_idx,
                'url': url,
                'success': True,
                'is_related': is_related,
                'related_group': related_group,
                'before_edit_path': content_path
            }
            
        except Exception as e:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': f'Failed to process attachment: {str(e)}'
            }
    
    def fetch_raw_diff(self, owner, repo, commit_sha):
        
        try:
            raw_diff_url = f"https://github.com/{owner}/{repo}/commit/{commit_sha}.diff"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            print(f"  Fetching raw diff from {raw_diff_url}")
            response = requests.get(raw_diff_url, headers=headers)
            
            if response.status_code != 200:
                print(f"  Failed to fetch raw diff: status code {response.status_code}")
                return None
                
            diff_content = response.text
   
            message = ""
            first_line = diff_content.split('\n', 1)[0] if diff_content else ""
            if first_line.startswith('From ') and '\n' in diff_content:
                
                second_line = diff_content.split('\n', 2)[1] if len(diff_content.split('\n')) > 1 else ""
                if second_line and not second_line.startswith('diff --git'):
                    message = second_line.strip()
            
          
            file_diffs = re.split(r'diff --git ', diff_content)
            
           
            if file_diffs and not file_diffs[0].strip().startswith('a/'):
                file_diffs = file_diffs[1:]
                
          
            for i in range(len(file_diffs)):
                if i > 0:  
                    file_diffs[i] = 'diff --git ' + file_diffs[i]
            
            changes = []
            for file_diff in file_diffs:
             
                filename_match = re.search(r'a/(.*?) b/', file_diff)
                if not filename_match:
                    continue
                    
                filename = filename_match.group(1)
                if not self._is_code_file(filename):
                    continue
                    
            
                before_content, after_content = self._extract_code_from_patch(file_diff)
                
          
                if not before_content and not after_content:
                    continue
                
                changes.append({
                    'filename': filename,
                    'status': 'modified', 
                    'before_content': before_content,
                    'after_content': after_content
                })
            
            if not message:
                message = f"Commit {commit_sha}"
                
            return {
                'message': message,
                'changes': changes
            }
            
        except Exception as e:
            print(f"  Error fetching raw diff: {e}")
            return None
    
    def process_github_commit(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
       
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid GitHub commit URL'
            }
        
        owner, repo, commit_sha = match.groups()
        
     
        commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
        response = self.github_api_request(commit_url)
        if not response:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Failed to fetch commit data'
            }
        
        commit_data = response.json()
        
        code_changes = []
        for file_data in commit_data.get('files', []):
            filename = file_data.get('filename', '')
            
       
            if not self._is_code_file(filename):
                continue
            
          
            before_content = None
            after_content = None
            
          
            patch = file_data.get('patch')
            if patch:
                before_content, after_content = self._extract_code_from_patch(patch)
            
       
            if not before_content or not after_content:
                parent_sha = commit_data.get('parents', [{}])[0].get('sha') if commit_data.get('parents') else None
                
                if parent_sha and file_data.get('status') != 'added':
                    before_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", parent_sha)
                
                if file_data.get('status') != 'removed':
                    after_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", commit_sha)
            
            code_changes.append({
                'filename': filename,
                'status': file_data.get('status', ''),
                'before_content': before_content,
                'after_content': after_content
            })
        
     
        if code_changes:
            file_name = f"{owner}_{repo}_commit_{commit_sha[:7]}"
            before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
            after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
            
        
            before_changes = {
                'url': url,
                'type': 'github_commit',
                'owner': owner,
                'repo': repo,
                'commit_sha': commit_sha,
                'commit_message': commit_data.get('commit', {}).get('message', ''),
                'code_changes': [
                    {
                        'filename': change['filename'],
                        'status': change['status'],
                        'content': change['before_content']
                    }
                    for change in code_changes
                    if change['before_content']
                ]
            }
            
            with open(before_edit_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(before_changes)
                f.write(formatted_json)
            
          
            after_changes = {
                'url': url,
                'type': 'github_commit',
                'owner': owner,
                'repo': repo,
                'commit_sha': commit_sha,
                'commit_message': commit_data.get('commit', {}).get('message', ''),
                'code_changes': [
                    {
                        'filename': change['filename'],
                        'status': change['status'],
                        'content': change['after_content']
                    }
                    for change in code_changes
                    if change['after_content']
                ]
            }
            
            with open(after_edit_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(after_changes)
                f.write(formatted_json)
            
            return {
                'row_idx': row_idx,
                'url': url,
                'success': True,
                'is_related': is_related,
                'related_group': related_group,
                'before_edit_path': before_edit_path,
                'after_edit_path': after_edit_path
            }
        else:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'No code changes found in commit'
            }
    
    def process_jira_issue(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
       
       
        match = re.search(r'browse/([A-Z]+-\d+)', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid JIRA issue URL'
            }
        
        issue_key = match.group(1)
        
        
        api_url = f"{self.jira_base_url}/rest/api/2/issue/{issue_key}"
        try:
            response = requests.get(api_url)
            response.raise_for_status()
            issue_data = response.json()
        except requests.exceptions.RequestException as e:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': f'Failed to fetch issue data: {str(e)}'
            }
        
       
        description = issue_data.get('fields', {}).get('description', '')
        code_blocks = self._extract_code_blocks_from_text(description)
        
        
        if issue_key.startswith('FLINK-') and not code_blocks:
            xml_blocks = self._extract_xml_from_jira_description(description)
            code_blocks.extend(xml_blocks)
        
     
        comments_url = f"{api_url}/comment"
        try:
            response = requests.get(comments_url)
            if response.status_code == 200:
                comments_data = response.json()
                for comment in comments_data.get('comments', []):
                    comment_body = comment.get('body', '')
                    code_blocks.extend(self._extract_code_blocks_from_text(comment_body))
                    
                  
                    if issue_key.startswith('FLINK-') and not code_blocks:
                        xml_blocks = self._extract_xml_from_jira_description(comment_body)
                        code_blocks.extend(xml_blocks)
        except requests.exceptions.RequestException:
           
            pass
        
       
        attachments = issue_data.get('fields', {}).get('attachment', [])
        patch_attachments = [att for att in attachments if att.get('filename', '').endswith('.patch')]
        
        for attachment in patch_attachments:
            try:
                att_url = attachment.get('content')
                if att_url:
                    response = requests.get(att_url, headers={'X-Atlassian-Token': 'no-check'})
                    if response.status_code == 200:
                        patch_content = response.text
                        before_content, after_content = self._extract_code_from_patch(patch_content)
                        if before_content:
                            code_blocks.append(before_content)
                        if after_content:
                            code_blocks.append(after_content)
            except requests.exceptions.RequestException:
               
                pass
        
        
        if code_blocks:
            file_name = f"jira_{issue_key}"
            before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
            
            
            before_changes = {
                'url': url,
                'type': 'jira_issue',
                'issue_key': issue_key,
                'title': issue_data.get('fields', {}).get('summary', ''),
                'code_blocks': code_blocks,
                'issue_title': additional_info['issue_title'],
                'issue_url': additional_info['issue_url']
            }
            
            with open(before_edit_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(before_changes)
                f.write(formatted_json)
            
            return {
                'row_idx': row_idx,
                'url': url,
                'success': True,
                'is_related': is_related,
                'related_group': related_group,
                'before_edit_path': before_edit_path,
                'code_blocks': code_blocks  
            }
        else:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'No code blocks found in issue'
            }
    
    def process_jira_patch(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
        try:
            
            match = re.search(r'attachment/(\d+)/([^/]+)', url)
            if not match:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Invalid JIRA patch URL'
                }
            
            patch_id = match.group(1)
            patch_filename = match.group(2)
            
           
            response = requests.get(url, headers={'X-Atlassian-Token': 'no-check'})
            response.raise_for_status()
            patch_content = response.text
            
           
            before_content, after_content = self._extract_code_from_patch(patch_content)
            
           
            if before_content or after_content:
                file_name = f"jira_patch_{patch_id}"
                
                
                if before_content:
                    before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                    before_changes = {
                        'url': url,
                        'type': 'jira_patch',
                        'patch_id': patch_id,
                        'filename': patch_filename,
                        'content': before_content,
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(before_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(before_changes)
                        f.write(formatted_json)
                else:
                    before_edit_path = None
                
                
                if after_content:
                    after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                    after_changes = {
                        'url': url,
                        'type': 'jira_patch',
                        'patch_id': patch_id,
                        'filename': patch_filename,
                        'content': after_content,
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(after_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(after_changes)
                        f.write(formatted_json)
                else:
                    after_edit_path = None
                
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'before_edit_path': before_edit_path,
                    'after_edit_path': after_edit_path
                }
            else:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'No code changes found in patch'
                }
        except requests.exceptions.RequestException as e:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': f'Failed to fetch patch: {str(e)}'
            }
    
    def fetch_pr_commits(self, owner, repo, pr_number):
        
        commits_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/commits"
        response = self.github_api_request(commits_url)
        if response:
            return response.json()
        return []
        
    def process_github_pr_commits(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
       
        pr_commit_match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/commits/([a-f0-9]+)', url)
        if pr_commit_match:
            owner, repo, pr_number, commit_sha = pr_commit_match.groups()
            
          
            commit_url = f"https://github.com/{owner}/{repo}/commit/{commit_sha}"
            print(f"  Processing PR commit as regular commit: {commit_url}")
            
          
            diff_data = self.fetch_raw_diff(owner, repo, commit_sha)
            if diff_data and diff_data.get('changes'):
                print(f"  Successfully extracted changes using raw diff")
               
                file_name = f"{owner}_{repo}_pr_{pr_number}_commit_{commit_sha[:7]}"
                before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                
               
                before_changes = {
                    'url': url,
                    'type': 'github_pr_commit',
                    'owner': owner,
                    'repo': repo,
                    'pr_number': pr_number,
                    'commit_sha': commit_sha,
                    'commit_message': diff_data.get('message', ''),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['before_content']
                        }
                        for change in diff_data['changes']
                        if change['before_content']
                    ]
                }
                
                with open(before_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(before_changes)
                    f.write(formatted_json)
                
              
                after_changes = {
                    'url': url,
                    'type': 'github_pr_commit',
                    'owner': owner,
                    'repo': repo,
                    'pr_number': pr_number,
                    'commit_sha': commit_sha,
                    'commit_message': diff_data.get('message', ''),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['after_content']
                        }
                        for change in diff_data['changes']
                        if change['after_content']
                    ]
                }
                
                with open(after_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(after_changes)
                    f.write(formatted_json)
                
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'before_edit_path': before_edit_path,
                    'after_edit_path': after_edit_path
                }
            
          
            result = self.process_github_commit_web(commit_url, row_idx, is_related, related_group)
            if result['success']:
                
                if 'before_edit_path' in result and result['before_edit_path']:
                    old_path = result['before_edit_path']
                    new_path = old_path.replace('_commit_', f'_pr_{pr_number}_commit_')
                    os.rename(old_path, new_path)
                    result['before_edit_path'] = new_path
                
                if 'after_edit_path' in result and result['after_edit_path']:
                    old_path = result['after_edit_path']
                    new_path = old_path.replace('_commit_', f'_pr_{pr_number}_commit_')
                    os.rename(old_path, new_path)
                    result['after_edit_path'] = new_path
                
                return result
            
          
            try:
              
                commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
                response = self.github_api_request(commit_url)
                if response:
                    commit_data = response.json()
                    
                 
                    code_changes = []
                    for file_data in commit_data.get('files', []):
                        filename = file_data.get('filename', '')
                        
                       
                        if not self._is_code_file(filename):
                            continue
                        
                        before_content = None
                        after_content = None
                        
                 
                        patch = file_data.get('patch')
                        if patch:
                            before_content, after_content = self._extract_code_from_patch(patch)
                        
                        
                        if not before_content or not after_content:
                            parent_sha = commit_data.get('parents', [{}])[0].get('sha') if commit_data.get('parents') else None
                            
                            if parent_sha and file_data.get('status') != 'added':
                                before_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", parent_sha)
                            
                            if file_data.get('status') != 'removed':
                                after_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", commit_sha)
                        
                        code_changes.append({
                            'filename': filename,
                            'status': file_data.get('status', ''),
                            'before_content': before_content,
                            'after_content': after_content
                        })
                    
               
                    if code_changes:
                        file_name = f"{owner}_{repo}_pr_{pr_number}_commit_{commit_sha[:7]}"
                        before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                        after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                        
                      
                        before_changes = {
                            'url': url,
                            'type': 'github_pr_commit',
                            'owner': owner,
                            'repo': repo,
                            'pr_number': pr_number,
                            'commit_sha': commit_sha,
                            'commit_message': commit_data.get('commit', {}).get('message', ''),
                            'code_changes': [
                                {
                                    'filename': change['filename'],
                                    'status': change['status'],
                                    'content': change['before_content']
                                }
                                for change in code_changes
                                if change['before_content']
                            ]
                        }
                        
                        with open(before_edit_path, 'w', encoding='utf-8') as f:
                            formatted_json = self._format_json_with_multiline_code(before_changes)
                            f.write(formatted_json)
                        
                 
                        after_changes = {
                            'url': url,
                            'type': 'github_pr_commit',
                            'owner': owner,
                            'repo': repo,
                            'pr_number': pr_number,
                            'commit_sha': commit_sha,
                            'commit_message': commit_data.get('commit', {}).get('message', ''),
                            'code_changes': [
                                {
                                    'filename': change['filename'],
                                    'status': change['status'],
                                    'content': change['after_content']
                                }
                                for change in code_changes
                                if change['after_content']
                            ]
                        }
                        
                        with open(after_edit_path, 'w', encoding='utf-8') as f:
                            formatted_json = self._format_json_with_multiline_code(after_changes)
                            f.write(formatted_json)
                        
                        return {
                            'row_idx': row_idx,
                            'url': url,
                            'success': True,
                            'is_related': is_related,
                            'related_group': related_group,
                            'before_edit_path': before_edit_path,
                            'after_edit_path': after_edit_path
                        }
            except Exception as e:
                print(f"Exception when processing PR commit via API: {e}")
        
    
        try:
         
            match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)', url)
            if not match:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Invalid GitHub PR URL'
                }
            
            owner, repo, pr_number = match.groups()
            
  
            pr_api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
            response = self.github_api_request(pr_api_url)
            if not response:
                         
                print(f"API request failed for {url}, trying web scraping...")
                return self.process_github_pr_web(url, row_idx, is_related, related_group, additional_info)
            
            pr_data = response.json()
            
    
            commits = self.fetch_pr_commits(owner, repo, pr_number)
            if not commits:
              
                print(f"Failed to fetch commits for PR {pr_number}, trying web scraping...")
                return self.process_github_pr_web(url, row_idx, is_related, related_group)
            
        
            commit_results = []
            for commit_idx, commit in enumerate(commits):
                commit_sha = commit.get('sha')
                if not commit_sha:
                    continue
                
               
                commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
                response = self.github_api_request(commit_url)
                if not response:
                    print(f"Error fetching commit {commit_sha}")
                    continue
                    
                commit_data = response.json()
                
              
                code_changes = []
                for file_data in commit_data.get('files', []):
                    filename = file_data.get('filename', '')
                    
                
                    if not self._is_code_file(filename):
                        continue
                    
                 
                    before_content = None
                    after_content = None
                    
                  
                    patch = file_data.get('patch')
                    if patch:
                        before_content, after_content = self._extract_code_from_patch(patch)
                    
                   
                    if not before_content or not after_content:
                        parent_sha = commit_data.get('parents', [{}])[0].get('sha') if commit_data.get('parents') else None
                        
                        if parent_sha and file_data.get('status') != 'added':
                            before_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", parent_sha)
                        
                        if file_data.get('status') != 'removed':
                            after_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", commit_sha)
                    
                    code_changes.append({
                        'filename': filename,
                        'status': file_data.get('status', ''),
                        'before_content': before_content,
                        'after_content': after_content
                    })
                
            
                if not code_changes:
                    diff_data = self.fetch_raw_diff(owner, repo, commit_sha)
                    if diff_data and diff_data.get('changes'):
                        code_changes = diff_data.get('changes', [])
                
                
                if code_changes:
                    file_name = f"{owner}_{repo}_pr_{pr_number}_commit_{commit_idx}_{commit_sha[:7]}"
                    before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                    after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                    
               
                    before_changes = {
                        'url': url,
                        'type': 'github_pr_commit',
                        'owner': owner,
                        'repo': repo,
                        'pr_number': pr_number,
                        'commit_sha': commit_sha,
                        'commit_message': commit.get('commit', {}).get('message', ''),
                        'code_changes': [
                            {
                                'filename': change['filename'],
                                'status': change['status'],
                                'content': change['before_content']
                            }
                            for change in code_changes
                            if change['before_content']
                        ],
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(before_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(before_changes)
                        f.write(formatted_json)
                    
                  
                    after_changes = {
                        'url': url,
                        'type': 'github_pr_commit',
                        'owner': owner,
                        'repo': repo,
                        'pr_number': pr_number,
                        'commit_sha': commit_sha,
                        'commit_message': commit.get('commit', {}).get('message', ''),
                        'code_changes': [
                            {
                                'filename': change['filename'],
                                'status': change['status'],
                                'content': change['after_content']
                            }
                            for change in code_changes
                            if change['after_content']
                        ],
                        'issue_title': additional_info['issue_title'],
                        'issue_url': additional_info['issue_url']
                    }
                    
                    with open(after_edit_path, 'w', encoding='utf-8') as f:
                        formatted_json = self._format_json_with_multiline_code(after_changes)
                        f.write(formatted_json)
                    
                    commit_results.append({
                        'commit_sha': commit_sha,
                        'success': True,
                        'before_edit_path': before_edit_path,
                        'after_edit_path': after_edit_path
                    })
            
    
            if commit_results:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'commit_results': commit_results,
                    'num_commits_processed': len(commit_results)
                }
            else:
                
                print(f"No commits processed successfully for PR {pr_number}, trying web scraping...")
                return self.process_github_pr_web(url, row_idx, is_related, related_group, additional_info)
        except Exception as e:
         
            print(f"Exception when processing PR via API: {e}, trying web scraping...")
            return self.process_github_pr_web(url, row_idx, is_related, related_group, additional_info)
    
    def process_github_pr(self, url, row_idx, is_related=False, related_group=None):
        
       
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid GitHub PR URL'
            }
        
        owner, repo, pr_number = match.groups()
        
    
        pr_api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        response = self.github_api_request(pr_api_url)
        if not response:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': f'Failed to fetch PR data'
            }
        
        pr_data = response.json()
        

        files_url = f"{pr_api_url}/files"
        response = self.github_api_request(files_url)
        if not response:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': f'Failed to fetch PR files'
            }
        
        files_data = response.json()
        

        code_changes = []
        for file_data in files_data:
            filename = file_data.get('filename', '')
            
      
            if not self._is_code_file(filename):
                continue
            
         
            before_content = None
            after_content = None
            
          
            patch = file_data.get('patch')
            if patch:
                before_content, after_content = self._extract_code_from_patch(patch)
            
          
            if not before_content or not after_content:
                if file_data.get('status') != 'added':
                    before_content = self._fetch_github_raw_content(owner, repo, file_data.get('contents_url'), pr_data.get('base', {}).get('sha'))
                
                if file_data.get('status') != 'removed':
                    after_content = self._fetch_github_raw_content(owner, repo, file_data.get('contents_url'), pr_data.get('head', {}).get('sha'))
            
            code_changes.append({
                'filename': filename,
                'status': file_data.get('status', ''),
                'before_content': before_content,
                'after_content': after_content
            })
        
  
        if code_changes:
            file_name = f"{owner}_{repo}_pr_{pr_number}"
            before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
            after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
            
         
            before_changes = {
                'url': url,
                'type': 'github_pr',
                'owner': owner,
                'repo': repo,
                'pr_number': pr_number,
                'title': pr_data.get('title', ''),
                'code_changes': [
                    {
                        'filename': change['filename'],
                        'status': change['status'],
                        'content': change['before_content']
                    }
                    for change in code_changes
                    if change['before_content']
                ]
            }
            
            with open(before_edit_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(before_changes)
                f.write(formatted_json)
            
    
            after_changes = {
                'url': url,
                'type': 'github_pr',
                'owner': owner,
                'repo': repo,
                'pr_number': pr_number,
                'title': pr_data.get('title', ''),
                'code_changes': [
                    {
                        'filename': change['filename'],
                        'status': change['status'],
                        'content': change['after_content']
                    }
                    for change in code_changes
                    if change['after_content']
                ]
            }
            
            with open(after_edit_path, 'w', encoding='utf-8') as f:
                formatted_json = self._format_json_with_multiline_code(after_changes)
                f.write(formatted_json)
            
            return {
                'row_idx': row_idx,
                'url': url,
                'success': True,
                'is_related': is_related,
                'related_group': related_group,
                'before_edit_path': before_edit_path,
                'after_edit_path': after_edit_path
            }
        else:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'No code changes found in PR'
            }
    
    def process_github_blob(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
  
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*?)(?:#L\d+(?:-L\d+)?)?$', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid GitHub blob URL'
            }
        
        owner, repo, ref, file_path = match.groups()
        
  
        line_match = re.search(r'#L(\d+)(?:-L(\d+))?$', url)
        start_line = int(line_match.group(1)) if line_match else None
        end_line = int(line_match.group(2)) if line_match and line_match.group(2) else start_line
        
    
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{file_path}"
        response = self.github_api_request(raw_url)
        if not response:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Failed to fetch file content'
            }
        
        content = response.text
        
   
        if start_line and end_line:
            lines = content.split('\n')
            if start_line <= len(lines) and end_line <= len(lines):
             
                content = '\n'.join(lines[start_line-1:end_line])
        
       
        if not self._is_code_file(file_path):
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Not a recognized code file'
            }
        
     
        file_name = f"{owner}_{repo}_blob_{ref.replace('/', '_')}_{file_path.replace('/', '_')}"
        if len(file_name) > 100:  
            file_name = file_name[:100] + '_' + str(hash(file_name) % 10000)
            
        before_edit_path = f'log_security/data/code_changes/{file_name}_content.json'
        
     
        content_data = {
            'url': url,
            'type': 'github_blob',
            'owner': owner,
            'repo': repo,
            'ref': ref,
            'file_path': file_path,
            'start_line': start_line,
            'end_line': end_line,
            'content': content,
            'issue_title': additional_info['issue_title'],
            'issue_url': additional_info['issue_url']
            }
        
        with open(before_edit_path, 'w', encoding='utf-8') as f:
            formatted_json = self._format_json_with_multiline_code(content_data)
            f.write(formatted_json)
        
        return {
            'row_idx': row_idx,
            'url': url,
            'success': True,
            'is_related': is_related,
            'related_group': related_group,
            'before_edit_path': before_edit_path
        }
    
    def _is_code_file(self, filename):
        
     
        if not filename:
            return False
            
        filename = filename.lower()
        
       
        binary_extensions = [
            '.bin', '.exe', '.dll', '.so', '.dylib', '.obj', '.o', '.a', '.lib',
            '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.tif', '.tiff',
            '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar', '.7z', '.jar', '.war',
            '.ear', '.class', '.pyc', '.pyd', '.pyo', '.whl', '.egg', '.msi',
            '.dmg', '.iso', '.img', '.vhd', '.vmdk', '.vdi', '.qcow2', '.pcap',
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt',
            '.ods', '.odp', '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.wav',
            '.aac', '.flac', '.ogg', '.woff', '.woff2', '.eot', '.ttf', '.otf'
        ]
        
       
        if any(filename.endswith(ext) for ext in binary_extensions):
            return False
        
        
        code_extensions = [
            
            '.java', '.py', '.js', '.c', '.cpp', '.cs', '.go', '.rb', '.php',
            '.scala', '.kt', '.ts', '.sh', '.pl', '.pm', '.swift', '.m',
            '.h', '.cc', '.cxx', '.hpp', '.hxx', '.rs', '.dart', '.groovy',
            '.jsx', '.tsx', '.vue', '.coffee', '.lua', '.r', '.clj', '.ex', '.exs',
            '.erl', '.fs', '.fsx', '.hs', '.jl', '.nim', '.ml', '.elm', '.tf', '.tfvars',
            
            
            '.xml', '.json', '.yml', '.yaml', '.properties', '.conf', '.cfg',
            '.ini', '.toml', '.gradle', '.pom', '.project', '.classpath',
            '.lock', '.env', '.editorconfig', '.gitignore', '.dockerignore',
            
          
            '.css', '.scss', '.sass', '.less', '.html', '.htm', '.xhtml',
            '.jsp', '.asp', '.aspx', '.cshtml', '.php', '.phtml',
            
        
            '.md', '.markdown', '.txt', '.rst', '.adoc', '.textile',
            
      
            '.make', '.mk', '.cmake', '.bazel', '.bzl', '.build',
            '.gradle', '.sbt', '.maven', '.ant', '.pom',
            
      
            '.sql', '.hql', '.pgsql', '.tsql',
            
        
            '.log', '.out', '.err',
            
            
            '.proto', '.thrift', '.avsc', '.graphql', '.gql', '.wsdl',
            '.bat', '.cmd', '.ps1', '.psm1', '.bash', '.zsh', '.fish',
            '.patch', '.diff'
        ]
        
       
        code_filenames = [
            'dockerfile', 'jenkinsfile', 'vagrantfile', 'makefile', 'rakefile',
            'gemfile', 'procfile', 'brewfile', 'berksfile', 'fastfile',
            'podfile', 'gruntfile', 'gulpfile', '.gitconfig', '.npmrc',
            '.yarnrc', '.babelrc', '.eslintrc', '.prettierrc', '.stylelintrc',
            'tsconfig.json', 'package.json', 'composer.json', 'cargo.toml',
            'go.mod', 'go.sum', 'requirements.txt', 'pipfile', 'setup.py',
            'build.gradle', 'pom.xml', 'build.sbt', 'project.clj'
        ]
        
   
        if any(filename.endswith(ext) for ext in code_extensions):
            return True
            
       
        basename = os.path.basename(filename).lower()
        if basename in code_filenames:
            return True
            
      
        if any(part in filename for part in ['src/', 'lib/', 'include/', 'test/', 'tests/']):
            return True
            
        return False
        
    def _is_binary_or_key_content(self, content):
       
        if not content or not isinstance(content, str):
            return False
            
       
        if len(content.strip()) < 10:
            return False
        
      
        hex_array_pattern = r'^\s*U\d+\s*=\s*\[\s*(?:0x[0-9a-fA-F]+\s*,?\s*)+\]\s*$'
        if re.match(hex_array_pattern, content.strip(), re.MULTILINE):
            print("Detected hex array pattern")
            return True
      
        hex_chunks = re.findall(r'0x[0-9a-fA-F]+', content)
        if hex_chunks and len(hex_chunks) > 10:  
            content_length = len(content)
            hex_chars = sum(len(chunk) for chunk in hex_chunks)
          
            if hex_chars / content_length > 0.7: 
                print(f"Detected high density of hex values: {hex_chars/content_length:.2f}")
                return True
        
     
        hex_lines = re.findall(r'^[0-9a-fA-F]{32,}$', content, re.MULTILINE) 
        if hex_lines and len(hex_lines) > 5:  
            print(f"Detected {len(hex_lines)} lines of long hex strings")
            return True
        
       
        base64_pattern = r'^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$'
        lines = content.strip().split('\n')
        if lines:
            base64_lines = [line for line in lines if len(line.strip()) > 40 and re.match(base64_pattern, line.strip())]
            if base64_lines and len(base64_lines) / len(lines) > 0.7:  
                print(f"Detected high density of base64 data: {len(base64_lines)}/{len(lines)}")
                return True
        
      
        sample_size = min(1000, len(content))  
        sample = content[:sample_size]
        non_printable_chars = sum(1 for c in sample if ord(c) < 32 and c not in '\t\n\r')
        if non_printable_chars > 10: 
            print(f"Detected {non_printable_chars} non-printable characters")
            return True
        
        key_patterns = [
            r'-----BEGIN (RSA |DSA |OPENSSH |PGP |)PRIVATE KEY-----',
            r'-----BEGIN CERTIFICATE-----',
            r'ssh-rsa [A-Za-z0-9+/]{20,}',  
            r'api[_-]?key\s*[:=]\s*[\'"][A-Za-z0-9]{16,}[\'"]', 
            r'token\s*[:=]\s*[\'"][A-Za-z0-9]{16,}[\'"]', 
            r'password\s*[:=]\s*[\'"][^\'"]{8,}[\'"]' 
        ]
        for pattern in key_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                print(f"Detected encryption key pattern: {pattern}")
                return True
        
        return False
    
    def _extract_code_blocks_from_text(self, text):
        
        if not text:
            return []
        
 
        code_blocks = []
        
      
        pattern = r'```(?:\w+)?\s*\n(.*?)\n```'
        matches = re.finditer(pattern, text, re.DOTALL)
        for match in matches:
            code_blocks.append(match.group(1).strip())
        
       
        lines = text.split('\n')
        current_block = []
        in_block = False
        
        for line in lines:
            if line.startswith('    ') and not line.startswith('     '):
                in_block = True
                current_block.append(line[4:])
            elif in_block and line.strip() == '':
                current_block.append('')
            elif in_block:
                code_blocks.append('\n'.join(current_block))
                current_block = []
                in_block = False
        
        if in_block:
            code_blocks.append('\n'.join(current_block))
        
 
        if not code_blocks:
       
            code_patterns = [
             
                r'(?:public|private|protected)?\s+(?:static|final|abstract)?\s*class\s+\w+\s*(?:extends|implements)?\s*\w*\s*\{.*?\}',
              
                r'(?:public|private|protected)?\s+(?:static|final|abstract)?\s*\w+\s+\w+\s*\([^\)]*\)\s*\{.*?\}',
         
                r'class\s+\w+(?:\(\w+\))?:\s*.*?(?=\n\S)',
 
                r'def\s+\w+\s*\([^\)]*\):\s*.*?(?=\n\S)',
             
                r'<(?!!)(?:[a-zA-Z][a-zA-Z0-9]*:)?[a-zA-Z][a-zA-Z0-9]*(?:\s+[^>]*)?>.*?</(?:[a-zA-Z][a-zA-Z0-9]*:)?[a-zA-Z][a-zA-Z0-9]*>'
            ]
            
            for pattern in code_patterns:
                matches = re.finditer(pattern, text, re.DOTALL)
                for match in matches:
                    code_blocks.append(match.group(0).strip())
        

        if not code_blocks:
            
            potential_code_sections = re.split(r'\n\s*\n', text)  
            for section in potential_code_sections:
               
                if any(keyword in section for keyword in ['class ', 'public ', 'private ', 'static ', 'def ', 'import ', 'package ', 'function ', '<parent>', '</parent>', '<artifactId>', '<dependencies>']):
                    if len(section.strip().split('\n')) > 2:  
                        code_blocks.append(section.strip())
        
      
        if not code_blocks:
            xml_pattern = r'<[^>]+>.*?</[^>]+>|<[^>]+/>'
            xml_matches = re.finditer(xml_pattern, text, re.DOTALL)
            xml_blocks = []
            for match in xml_matches:
                xml_block = match.group(0).strip()
                if len(xml_block.split('\n')) > 2: 
                    xml_blocks.append(xml_block)
            
            if xml_blocks:
                code_blocks.extend(xml_blocks)
        
        return code_blocks
    
    def _extract_code_from_patch(self, patch_content):
       
        if not patch_content:
            return None, None
        
        before_lines = []
        after_lines = []
        
       
        is_unified_diff = '@@' in patch_content
        
       
        lines = patch_content.split('\n')
        in_hunk = False
        current_file = None
        
        for line in lines:
         
            if line.startswith('diff --git') or line.startswith('index ') or line.startswith('new file mode') or line.startswith('deleted file mode'):
                continue
                
          
            if line.startswith('--- '):
                current_file = 'before'
                continue
            if line.startswith('+++ '):
                current_file = 'after'
                continue
                
        
            if is_unified_diff:
       
                if line.startswith('@@'):
                    in_hunk = True
                    continue
                    
                if in_hunk:
                    if line.startswith('-'):
                        before_lines.append(line[1:])
                    elif line.startswith('+'):
                        after_lines.append(line[1:])
                    elif not line.startswith('\\'):  
                        before_lines.append(line)
                        after_lines.append(line)
            else:
              
                if line.startswith('-') and not line.startswith('---'):
                    before_lines.append(line[1:])
                elif line.startswith('+') and not line.startswith('+++'):
                    after_lines.append(line[1:])
                elif not line.startswith('@@') and not line.startswith('---') and not line.startswith('+++') and not line.startswith('diff --git'):
                
                    if not line.startswith('\\'):  
                        before_lines.append(line)
                        after_lines.append(line)
      
        if not before_lines and after_lines:
            
            before_content = None
            after_content = '\n'.join(after_lines).strip()
        elif before_lines and not after_lines:
          
            before_content = '\n'.join(before_lines).strip()
            after_content = None
        else:
            
            before_content = '\n'.join(before_lines).strip() if before_lines else None
            after_content = '\n'.join(after_lines).strip() if after_lines else None
        
        return before_content, after_content
    
    def _fetch_github_raw_content(self, owner, repo, contents_url, sha):
        
        if not contents_url or not sha:
            return None
        
       
        match = re.search(r'contents/(.+)$', contents_url)
        if not match:
            return None
        
        path = match.group(1)
        
     
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
        response = self.github_api_request(raw_url)
        if response and response.status_code == 200:
            return response.text
        
        return None
    
    def save_results_to_csv(self, results, output_path):
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['Row', 'URL', 'Success', 'Error', 'IsRelated', 'RelatedGroup', 'BeforeEditPath', 'AfterEditPath', 'NumCommits']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in results:
               
                if 'commit_results' in result and result['success']:
                    
                    summary_row = {
                        'Row': result['row_idx'],
                        'URL': result.get('url', ''),
                        'Success': result['success'],
                        'Error': '',
                        'IsRelated': result.get('is_related', False),
                        'RelatedGroup': result.get('related_group', ''),
                        'BeforeEditPath': '',
                        'AfterEditPath': '',
                        'NumCommits': result.get('num_commits_processed', 0)
                    }
                    writer.writerow(summary_row)
                    
                   
                    for commit_idx, commit_result in enumerate(result['commit_results']):
                        commit_row = {
                            'Row': f"{result['row_idx']}.{commit_idx+1}",
                            'URL': f"{result.get('url', '')}/commits/{commit_result['commit_sha']}",
                            'Success': commit_result['success'],
                            'Error': '',
                            'IsRelated': result.get('is_related', False),
                            'RelatedGroup': result.get('related_group', ''),
                            'BeforeEditPath': commit_result.get('before_edit_path', ''),
                            'AfterEditPath': commit_result.get('after_edit_path', '')
                        }
                        writer.writerow(commit_row)
                else:
                  
                    row = {
                        'Row': result['row_idx'],
                        'URL': result.get('url', ''),
                        'Success': result['success'],
                        'Error': result.get('error', ''),
                        'IsRelated': result.get('is_related', False),
                        'RelatedGroup': result.get('related_group', ''),
                        'BeforeEditPath': result.get('before_edit_path', ''),
                        'AfterEditPath': result.get('after_edit_path', ''),
                        'NumCommits': 0
                    }
                    writer.writerow(row)
    
    def _format_json_with_multiline_code(self, data):
       
        
        processed_data = self._process_code_content(data)
        
     
        return json.dumps(processed_data, indent=2, ensure_ascii=False)
    
    def _process_code_content(self, data):
        
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                if key == 'content' and isinstance(value, str):
                    
                    lines = value.split('\n')
                    if len(lines) > 1:
                        result[key] = '\n' + '\n'.join(lines)
                    else:
                        result[key] = value
                else:
                    result[key] = self._process_code_content(value)
            return result
        elif isinstance(data, list):
            return [self._process_code_content(item) for item in data]
        else:
            return data

    def _extract_xml_from_jira_description(self, text):
        
        if not text:
            return []
        
        xml_blocks = []
   
        xml_pattern = r'<(?!!)(?:[a-zA-Z][a-zA-Z0-9]*:)?[a-zA-Z][a-zA-Z0-9]*(?:\s+[^>]*)?>\s*.*?\s*</(?:[a-zA-Z][a-zA-Z0-9]*:)?[a-zA-Z][a-zA-Z0-9]*>'
        xml_matches = re.finditer(xml_pattern, text, re.DOTALL)
        
        for match in xml_matches:
            xml_block = match.group(0).strip()
            if len(xml_block.split('\n')) > 1: 
                xml_blocks.append(xml_block)
        

        if not xml_blocks:
          
            sections = re.split(r'\n\s*\n', text)
            for section in sections:
                if ('<' in section and '>' in section) and any(tag in section for tag in ['<parent>', '</parent>', '<artifactId>', '<dependencies>', '<build>', '<properties>']):
                    
                    xml_blocks.append(section.strip())
        
        
        if not xml_blocks:
           
            tag_pattern = r'<[^>]+>.*?</[^>]+>'
            tag_matches = re.finditer(tag_pattern, text, re.DOTALL)
            for match in tag_matches:
                xml_blocks.append(match.group(0).strip())
        
        return xml_blocks

    def fetch_github_content_from_web(self, url):
        
        try:
          
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                print(f"Failed to fetch content from web: {url}, status code: {response.status_code}")
                return None
           
            if '/blob/' in url:
                soup = BeautifulSoup(response.text, 'html.parser')
              
                code_element = soup.select_one('.blob-wrapper table')
                if code_element:
                 
                    code_lines = []
                    for line in code_element.select('tr'):
                        code_td = line.select_one('td.blob-code')
                        if code_td:
                            code_lines.append(code_td.get_text())
                    return '\n'.join(code_lines)
            
           
            elif '/commit/' in url:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                commit_message = soup.select_one('.commit-title')
                message = commit_message.get_text().strip() if commit_message else "Unknown commit message"
                
             
                changes = []
                
               
                file_diffs = soup.select('.file')
                
               
                if not file_diffs:
                    file_diffs = soup.select('[data-file-type]')
                
                if not file_diffs:
                    
                    file_headers = soup.select('.file-header')
                    if file_headers:
                        for header in file_headers:
                            parent = header.parent
                            if parent and parent not in file_diffs:
                                file_diffs.append(parent)
                
           
                for file_diff in file_diffs:
                   
                    filename = None
                    file_header = file_diff.select_one('.file-header')
                    
                    if file_header and file_header.has_attr('data-path'):
                        filename = file_header.get('data-path')
                    elif file_diff.has_attr('data-file-type'):
                       
                        filename_elem = file_diff.select_one('[data-path]')
                        if filename_elem:
                            filename = filename_elem.get('data-path')
                    
                    
                    if not filename:
                        filename_elem = file_diff.select_one('.file-info')
                        if filename_elem:
                            filename = filename_elem.get_text().strip()
                    
                    if not filename or not self._is_code_file(filename):
                        continue
                        
                  
                    before_content = []
                    after_content = []
                    
                    
                    code_lines = file_diff.select('.blob-code')
                    if not code_lines:
                        code_lines = file_diff.select('td[data-line-number]') 
                    
                    for line in code_lines:
                        line_text = line.get_text().strip()
                        line_class = line.get('class', '')
                        
                       
                        is_deletion = ('blob-code-deletion' in line_class or 
                                      'deletion' in line_class or 
                                      line.parent and 'deletion' in line.parent.get('class', ''))
                        
                        is_addition = ('blob-code-addition' in line_class or 
                                      'addition' in line_class or 
                                      line.parent and 'addition' in line.parent.get('class', ''))
                        
                        if is_deletion:
                            before_content.append(line_text)
                        elif is_addition:
                            after_content.append(line_text)
                        else:
                            before_content.append(line_text)
                            after_content.append(line_text)
                    
                   
                    if not before_content and not after_content:
                        all_content = []
                        for line in file_diff.select('td'):
                            line_text = line.get_text().strip()
                            if line_text:
                                all_content.append(line_text)
                        
                        if all_content:
                            
                            before_content = all_content
                            after_content = all_content
                    
                    changes.append({
                        'filename': filename,
                        'status': 'modified', 
                        'before_content': '\n'.join(before_content) if before_content else None,
                        'after_content': '\n'.join(after_content) if after_content else None
                    })
                
                
                if not changes:
                    print(f"No changes found with standard methods for {url}, trying alternative extraction...")
                    
                  
                    code_blocks = soup.select('pre')
                    for i, block in enumerate(code_blocks):
                        
                        if i % 2 == 0 and i+1 < len(code_blocks):
                            filename = f"unknown_file_{i//2}.txt"
                            before_content = block.get_text()
                            after_content = code_blocks[i+1].get_text()
                            
                            changes.append({
                                'filename': filename,
                                'status': 'modified',
                                'before_content': before_content,
                                'after_content': after_content
                    })
                
                return {
                    'message': message,
                    'changes': changes
                }
            
        
            elif '/pull/' in url:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Extract PR title
                pr_title = soup.select_one('.gh-header-title')
                title = pr_title.get_text().strip() if pr_title else "Unknown PR title"
                
               
                commits = []
                for commit_item in soup.select('.commits-list-item'):
                    commit_link = commit_item.select_one('.commit-id')
                    if commit_link and commit_link.has_attr('href'):
                        commit_url = f"https://github.com{commit_link['href']}"
                        commits.append(commit_url)
                
                return {
                    'title': title,
                    'commits': commits
                }
                
            return response.text
            
        except Exception as e:
            print(f"Error fetching content from web: {url}, error: {e}")
            return None
    
    def process_github_commit_web(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
        print(f"  Processing GitHub commit via web: {url}")
        
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid GitHub commit URL'
            }
        
        owner, repo, commit_sha = match.groups()
 
        raw_diff_data = self.fetch_raw_diff(owner, repo, commit_sha)
        if raw_diff_data and raw_diff_data.get('changes'):
            print(f"  Successfully extracted {len(raw_diff_data['changes'])} file changes from raw diff")
           
            commit_data = {
                'message': raw_diff_data.get('message', f"Commit {commit_sha}"),
                'changes': raw_diff_data.get('changes', [])
            }
        else:
           
            commit_data = self.fetch_github_content_from_web(url)
            
        if not commit_data:
            print(f"  Failed to fetch commit data from web for {url}, trying raw diff URL...")
            
           
            raw_diff_url = f"https://github.com/{owner}/{repo}/commit/{commit_sha}.diff"
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(raw_diff_url, headers=headers)
                if response.status_code == 200:
                   
                    diff_content = response.text
                    
                   
                    file_diffs = re.split(r'diff --git ', diff_content)
                    
                   
                    if file_diffs and not file_diffs[0].strip().startswith('a/'):
                        file_diffs = file_diffs[1:]
                    
                    changes = []
                    for file_diff in file_diffs:
                        
                        filename_match = re.search(r'a/(.*?) b/', file_diff)
                        if not filename_match:
                            continue
                            
                        filename = filename_match.group(1)
                        if not self._is_code_file(filename):
                            continue
                            
                      
                        before_content, after_content = self._extract_code_from_patch(file_diff)
                        
                        changes.append({
                            'filename': filename,
                            'status': 'modified',  
                            'before_content': before_content,
                            'after_content': after_content
                        })
                    
                  
                    commit_data = {
                        'message': f"Commit {commit_sha}",
                        'changes': changes
                    }
                    
                    print(f"  Successfully extracted {len(changes)} file changes from raw diff")
                else:
                    print(f"  Failed to fetch raw diff: status code {response.status_code}")
                    return {
                        'row_idx': row_idx,
                        'url': url,
                        'success': False,
                        'is_related': is_related,
                        'related_group': related_group,
                        'error': f'Failed to fetch commit data from web and raw diff'
                    }
            except Exception as e:
                print(f"  Error fetching raw diff: {e}")
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': f'Failed to fetch commit data: {str(e)}'
                }
        

        code_changes = commit_data.get('changes', [])
        if not code_changes:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'No code changes found in commit'
            }
        
    
        file_name = f"{owner}_{repo}_commit_{commit_sha[:7]}"
        before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
        after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
        
        before_changes = {
            'url': url,
            'type': 'github_commit',
            'owner': owner,
            'repo': repo,
            'commit_sha': commit_sha,
            'commit_message': commit_data.get('message', ''),
            'code_changes': [
                {
                    'filename': change['filename'],
                    'status': change['status'],
                    'content': change['before_content']
                }
                for change in code_changes
                if change['before_content']
            ]
        }
        
        with open(before_edit_path, 'w', encoding='utf-8') as f:
            formatted_json = self._format_json_with_multiline_code(before_changes)
            f.write(formatted_json)
        
       
        after_changes = {
            'url': url,
            'type': 'github_commit',
            'owner': owner,
            'repo': repo,
            'commit_sha': commit_sha,
            'commit_message': commit_data.get('message', ''),
            'code_changes': [
                {
                    'filename': change['filename'],
                    'status': change['status'],
                    'content': change['after_content']
                }
                for change in code_changes
                if change['after_content']
            ]
        }
        
        with open(after_edit_path, 'w', encoding='utf-8') as f:
            formatted_json = self._format_json_with_multiline_code(after_changes)
            f.write(formatted_json)
        
        return {
            'row_idx': row_idx,
            'url': url,
            'success': True,
            'is_related': is_related,
            'related_group': related_group,
            'before_edit_path': before_edit_path,
            'after_edit_path': after_edit_path
        }
    
    def process_github_pr_web(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
        print(f"  Processing GitHub PR via web: {url}")
        
     
        match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)', url)
        if not match:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Invalid GitHub PR URL'
            }
        
        owner, repo, pr_number = match.groups()
        
       
        pr_data = self.fetch_github_content_from_web(url)
        if not pr_data:
            return {
                'row_idx': row_idx,
                'url': url,
                'success': False,
                'is_related': is_related,
                'related_group': related_group,
                'error': 'Failed to fetch PR data from web'
            }
        
      
        commits = pr_data.get('commits', [])
        if commits:
            commit_results = []
            for commit_idx, commit_url in enumerate(commits):
             
                commit_result = self.process_github_commit_web(commit_url, row_idx, is_related, related_group)
                if commit_result['success']:
                    commit_sha = re.search(r'/commit/([a-f0-9]+)', commit_url).group(1)
                    commit_results.append({
                        'commit_sha': commit_sha,
                        'success': True,
                        'before_edit_path': commit_result.get('before_edit_path', ''),
                        'after_edit_path': commit_result.get('after_edit_path', '')
                    })
            
            if commit_results:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'commit_results': commit_results,
                    'num_commits_processed': len(commit_results)
                }
        
       
        try:
            
            diff_url = f"{url}.diff"
            response = requests.get(diff_url)
            if response.status_code != 200:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Failed to fetch PR diff'
                }
            
          
            diff_content = response.text
            code_changes = []
            
        
            file_diffs = re.split(r'diff --git', diff_content)
            for file_diff in file_diffs[1:]:  
           
                filename_match = re.search(r'a/(.+?) b/', file_diff)
                if not filename_match:
                    continue
                
                filename = filename_match.group(1)
 
                if not self._is_code_file(filename):
                    continue
                
            
                before_content, after_content = self._extract_code_from_patch(file_diff)
                
                if before_content or after_content:
                    code_changes.append({
                        'filename': filename,
                        'status': 'modified',  
                        'before_content': before_content,
                        'after_content': after_content
                    })
            
        
            if code_changes:
                file_name = f"{owner}_{repo}_pr_{pr_number}"
                before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                
           
                before_changes = {
                    'url': url,
                    'type': 'github_pr',
                    'owner': owner,
                    'repo': repo,
                    'pr_number': pr_number,
                    'title': pr_data.get('title', 'Unknown PR title'),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['before_content']
                        }
                        for change in code_changes
                        if change['before_content']
                    ],
                    'issue_title': additional_info['issue_title'],
                    'issue_url': additional_info['issue_url']
                }
                
                with open(before_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(before_changes)
                    f.write(formatted_json)
                
                
                after_changes = {
                    'url': url,
                    'type': 'github_pr',
                    'owner': owner,
                    'repo': repo,
                    'pr_number': pr_number,
                    'title': pr_data.get('title', 'Unknown PR title'),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['after_content']
                        }
                        for change in code_changes
                        if change['after_content']
                    ],
                    'issue_title': additional_info['issue_title'],
                    'issue_url': additional_info['issue_url']
                }
                
                with open(after_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(after_changes)
                    f.write(formatted_json)
                
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'before_edit_path': before_edit_path,
                    'after_edit_path': after_edit_path
                }
        except Exception as e:
            print(f"Error processing PR diff: {e}")
        
        return {
            'row_idx': row_idx,
            'url': url,
            'success': False,
            'is_related': is_related,
            'related_group': related_group,
            'error': 'No code changes found in PR'
        }
    
    def process_github_commit(self, url, row_idx, is_related=False, related_group=None, additional_info=None):
        
      
        try:
       
            match = re.match(r'https?://github\.com/([^/]+)/([^/]+)/commit/([a-f0-9]+)', url)
            if not match:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'Invalid GitHub commit URL'
                }
            
            owner, repo, commit_sha = match.groups()
            
      
            commit_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}"
            response = self.github_api_request(commit_url)
            if not response:
              
                print(f"API request failed for {url}, trying web scraping...")
                return self.process_github_commit_web(url, row_idx, is_related, related_group)
            
            commit_data = response.json()
            
        
            code_changes = []
            for file_data in commit_data.get('files', []):
                filename = file_data.get('filename', '')
                
        
                if not self._is_code_file(filename):
                    continue
                
           
                before_content = None
                after_content = None
          
                patch = file_data.get('patch')
                if patch:
                    before_content, after_content = self._extract_code_from_patch(patch)
                
            
                if not before_content or not after_content:
                    parent_sha = commit_data.get('parents', [{}])[0].get('sha') if commit_data.get('parents') else None
                    
                    if parent_sha and file_data.get('status') != 'added':
                        before_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", parent_sha)
                    
                    if file_data.get('status') != 'removed':
                        after_content = self._fetch_github_raw_content(owner, repo, f"contents/{filename}", commit_sha)
                
                code_changes.append({
                    'filename': filename,
                    'status': file_data.get('status', ''),
                    'before_content': before_content,
                    'after_content': after_content
                })
            
    
            if code_changes:
                file_name = f"{owner}_{repo}_commit_{commit_sha[:7]}"
                before_edit_path = f'log_security/data/code_changes/{file_name}_before_edit.json'
                after_edit_path = f'log_security/data/code_changes/{file_name}_after_edit.json'
                
    
                before_changes = {
                    'url': url,
                    'type': 'github_commit',
                    'owner': owner,
                    'repo': repo,
                    'commit_sha': commit_sha,
                    'commit_message': commit_data.get('commit', {}).get('message', ''),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['before_content']
                        }
                        for change in code_changes
                        if change['before_content']
                    ]
                }
                
                with open(before_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(before_changes)
                    f.write(formatted_json)
                
           
                after_changes = {
                    'url': url,
                    'type': 'github_commit',
                    'owner': owner,
                    'repo': repo,
                    'commit_sha': commit_sha,
                    'commit_message': commit_data.get('commit', {}).get('message', ''),
                    'code_changes': [
                        {
                            'filename': change['filename'],
                            'status': change['status'],
                            'content': change['after_content']
                        }
                        for change in code_changes
                        if change['after_content']
                    ]
                }
                
                with open(after_edit_path, 'w', encoding='utf-8') as f:
                    formatted_json = self._format_json_with_multiline_code(after_changes)
                    f.write(formatted_json)
                
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': True,
                    'is_related': is_related,
                    'related_group': related_group,
                    'before_edit_path': before_edit_path,
                    'after_edit_path': after_edit_path
                }
            else:
                return {
                    'row_idx': row_idx,
                    'url': url,
                    'success': False,
                    'is_related': is_related,
                    'related_group': related_group,
                    'error': 'No code changes found in commit'
                }
        except Exception as e:
           
            print(f"Exception when processing commit via API: {e}, trying web scraping...")
            return self.process_github_commit_web(url, row_idx, is_related, related_group)

    def generate_combined_results_csv(self, output_path='log_security/results/combined_result.csv'):
       
        print(f"Generating combined results CSV at {output_path}...")
        
       
        fieldnames = [
            'URL', 
            'Type', 
            'Owner', 
            'Repo', 
            'CommitSHA', 
            'PRNumber', 
            'IssueKey', 
            'Title', 
            'Message', 
            'Filename', 
            'Status', 
            'BeforeContent', 
            'AfterContent',
            'IssueTitle',
            'IssueURL'
        ]
        
    
        code_changes_dir = 'log_security/data/code_changes'
        json_files = [f for f in os.listdir(code_changes_dir) if f.endswith('.json')]
    
        file_groups = {}
        for json_file in json_files:
            base_name = json_file.replace('_before_edit.json', '').replace('_after_edit.json', '')
            if base_name not in file_groups:
                file_groups[base_name] = []
            file_groups[base_name].append(json_file)
        
      
        all_rows = []
        
       
        for base_name, files in file_groups.items():
            before_file = next((f for f in files if '_before_edit.json' in f), None)
            after_file = next((f for f in files if '_after_edit.json' in f), None)
            
            before_data = None
            after_data = None
            
          
            if before_file:
                try:
                    with open(os.path.join(code_changes_dir, before_file), 'r', encoding='utf-8') as f:
                        before_data = json.load(f)
                except Exception as e:
                    print(f"Error loading {before_file}: {e}")
            
            
            if after_file:
                try:
                    with open(os.path.join(code_changes_dir, after_file), 'r', encoding='utf-8') as f:
                        after_data = json.load(f)
                except Exception as e:
                    print(f"Error loading {after_file}: {e}")
            
           
            if before_data or after_data:
                
                data = before_data if before_data else after_data
                
            
                url = data.get('url', '')
                type_value = data.get('type', '')
                owner = data.get('owner', '')
                repo = data.get('repo', '')
                commit_sha = data.get('commit_sha', '')
                pr_number = data.get('pr_number', '')
                issue_key = data.get('issue_key', '')
                title = data.get('title', '')
                message = data.get('commit_message', '')
                issue_title = data.get('issue_title', '')
                issue_url = data.get('issue_url', '')
                
               
                if 'code_changes' in data:
                    
                    all_filenames = set()
                    before_changes = {}
                    after_changes = {}
                    
                   
                    if before_data and 'code_changes' in before_data:
                        for change in before_data['code_changes']:
                            filename = change.get('filename', '')
                            all_filenames.add(filename)
                            before_changes[filename] = {
                                'status': change.get('status', ''),
                                'content': change.get('content', '')
                            }
                    
                   
                    if after_data and 'code_changes' in after_data:
                        for change in after_data['code_changes']:
                            filename = change.get('filename', '')
                            all_filenames.add(filename)
                            after_changes[filename] = {
                                'status': change.get('status', ''),
                                'content': change.get('content', '')
                            }
                    
                  
                    for filename in all_filenames:
                        before_content = before_changes.get(filename, {}).get('content', '')
                        after_content = after_changes.get(filename, {}).get('content', '')
                        status = before_changes.get(filename, {}).get('status', '') or after_changes.get(filename, {}).get('status', '')
                        
                   
                        is_before_binary = self._is_binary_or_key_content(before_content)
                        is_after_binary = self._is_binary_or_key_content(after_content)
                        if is_before_binary or is_after_binary:
                            print(f"Skipping binary or key content in file: {filename}")
                            print(f"  URL: {url}")
                            print(f"  Before content binary: {is_before_binary}")
                            print(f"  After content binary: {is_after_binary}")
                            print(f"  Content preview: {before_content[:100]}..." if before_content else "No before content")
                            continue
                        
                        row = {
                            'URL': url,
                            'Type': type_value,
                            'Owner': owner,
                            'Repo': repo,
                            'CommitSHA': commit_sha,
                            'PRNumber': pr_number,
                            'IssueKey': issue_key,
                            'Title': title,
                            'Message': message,
                            'Filename': filename,
                            'Status': status,
                            'BeforeContent': before_content,
                            'AfterContent': after_content,
                            'IssueTitle': issue_title,
                            'IssueURL': issue_url
                        }
                        all_rows.append(row)
                elif 'content' in data:
                  
                    content = data.get('content', '')
                    
                   
                    if self._is_binary_or_key_content(content):
                        print(f"Skipping binary or key content in file: {data.get('filename', '')}")
                        print(f"  URL: {url}")
                        print(f"  Type: {type_value}")
                        print(f"  Content preview: {content[:100]}..." if content else "No content")
                        continue
                        
                    row = {
                        'URL': url,
                        'Type': type_value,
                        'Owner': owner,
                        'Repo': repo,
                        'CommitSHA': commit_sha,
                        'PRNumber': pr_number,
                        'IssueKey': issue_key,
                        'Title': title,
                        'Message': message,
                        'Filename': data.get('filename', ''),
                        'Status': '',
                        'BeforeContent': content,
                        'AfterContent': '',
                        'IssueTitle': issue_title,
                        'IssueURL': issue_url
                    }
                    all_rows.append(row)
                elif 'code_blocks' in data:
                    
                    for i, block in enumerate(data['code_blocks']):
                      
                        if self._is_binary_or_key_content(block):
                            print(f"Skipping binary or key content in code block {i+1}")
                            print(f"  URL: {url}")
                            print(f"  Type: {type_value}")
                            print(f"  Content preview: {block[:100]}..." if block else "No content")
                            continue
                            
                        row = {
                            'URL': url,
                            'Type': type_value,
                            'Owner': owner,
                            'Repo': repo,
                            'CommitSHA': commit_sha,
                            'PRNumber': pr_number,
                            'IssueKey': issue_key,
                            'Title': title,
                            'Message': message,
                            'Filename': f'code_block_{i+1}',
                            'Status': '',
                            'BeforeContent': block,
                            'AfterContent': '',
                            'IssueTitle': issue_title,
                            'IssueURL': issue_url
                        }
                        all_rows.append(row)
        
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in all_rows:
                writer.writerow(row)
        
        print(f"Combined results CSV generated with {len(all_rows)} rows")

def main():
    parser = argparse.ArgumentParser(description='Extract code changes from GitHub PRs, JIRA issues, and patches')
    parser.add_argument('--input', '-i', default='../data/SecLogging_Dataset.csv', help='Input CSV file path')
    parser.add_argument('--url-column', default='PR URL', help='Column name containing URLs')
    parser.add_argument('--output', '-o', default='log_security/results/code_changes_results.csv', help='Output results CSV path')
    parser.add_argument('--github-token', '-t', help='GitHub API token')
    parser.add_argument('--combined-output', '-c', default='log_security/results/combined_result.csv', help='Combined output CSV path')
    parser.add_argument('--skip-binary', action='store_true', help='Skip binary and key data detection')
    
    args = parser.parse_args()
    
    extractor = CodeChangeExtractor(github_token=args.github_token)
  
    if args.skip_binary:
        print("Binary and key data detection is disabled")
        extractor._is_binary_or_key_content = lambda content: False
    
    results = extractor.process_csv_file(args.input, args.url_column)
    
    extractor.save_results_to_csv(results, args.output)

    extractor.generate_combined_results_csv(args.combined_output)
    
    success_count = sum(1 for r in results if r['success'])
    failed_count = len(results) - success_count
    print(f"\nProcessing complete: {len(results)} items, {success_count} successful, {failed_count} failed")
    

    if failed_count > 0:
        print("\nFailed items:")
        for r in results:
            if not r['success']:
                print(f"  Row {r['row_idx']}: {r.get('url', 'No URL')} - {r.get('error', 'Unknown error')}")
    
    print(f"\nResults saved to: {args.output}")
    print(f"Combined results saved to: {args.combined_output}")
    print(f"Code changes saved to: log_security/data/code_changes/")



if __name__ == '__main__':
    
    if len(sys.argv) > 1 and sys.argv[1] == '--test-xml':
        test_jira_xml_extraction()
    else:
        main() 