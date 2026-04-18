#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import csv
import json
import os
import pandas as pd
import requests
import time
import re
from urllib.parse import urlparse
import openai
from openai import OpenAI


def estimate_tokens(text):
 
  
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    
 
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    
  
    other_chars = len(re.findall(r'[^a-zA-Z\u4e00-\u9fff\s]', text))
    
 
    estimated_tokens = english_words * 1.3 + chinese_chars + other_chars * 0.5
    
    return int(estimated_tokens)


class LogSecurityAnalyzer:
    def __init__(self, combined_csv_path, overview_csv_path, api_key=None, api_url=None, model="gpt-4o-mini", batch_size=50, use_description=False, use_explanation=False):
     
        self.combined_csv_path = combined_csv_path
        self.overview_csv_path = overview_csv_path
        
        self.api_key = api_key or "your api key"
       
        self.api_url = api_url
        
        self.model = model
        
        self.batch_size = batch_size if batch_size else 10
        
        self.use_description = use_description
        
        self.use_explanation = use_explanation
        self.client = None
        self.combined_data = None
        self.overview_data = None
        self.output_data = []
        
    def load_data(self):
        
        print(f"Loading combined data from {self.combined_csv_path}")
        
       
        encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']
        for encoding in encodings_to_try:
            try:
                print(f"Trying to load combined data with encoding: {encoding}")
                self.combined_data = pd.read_csv(self.combined_csv_path, encoding=encoding)
                print(f"Successfully loaded combined data with encoding: {encoding}")
                break
            except UnicodeDecodeError:
                print(f"Failed to load with encoding {encoding}, trying next...")
            except Exception as e:
                print(f"Error loading with encoding {encoding}: {e}")
        
        if self.combined_data is None:
            raise ValueError(f"Failed to load combined data from {self.combined_csv_path} with any encoding")
        
        print(f"Loading overview data from {self.overview_csv_path}")
        
       
        for encoding in encodings_to_try:
            try:
                print(f"Trying to load overview data with encoding: {encoding}")
                self.overview_data = pd.read_csv(self.overview_csv_path, encoding=encoding)
                print(f"Successfully loaded overview data with encoding: {encoding}")
                break
            except UnicodeDecodeError:
                print(f"Failed to load with encoding {encoding}, trying next...")
            except Exception as e:
                print(f"Error loading with encoding {encoding}: {e}")
        
        if self.overview_data is None:
            raise ValueError(f"Failed to load overview data from {self.overview_csv_path} with any encoding")
        
        print(f"Loaded {len(self.combined_data)} entries from combined data")
        print(f"Loaded {len(self.overview_data)} entries from overview data")
        
   
        self._validate_data_integrity()
    
    def match_urls(self):
        
        print("Matching URLs between datasets...")
        
   
        self.combined_data['IssueTitle'] = ''
        self.combined_data['CategoryI'] = ''
        self.combined_data['CategoryII'] = ''
 
        if self.use_description:
            self.combined_data['Description'] = ''
            print("Including Description column from overview CSV as a hint")
 
        url_to_issue = {}
        
  
        for _, row in self.overview_data.iterrows():
            pr_url = row.get('PR URL', '')
            issue_url = row.get('Issue URL', '')
            issue_title = row.get('Issue Title', '')
            category_i = row.get('Category I', '')
            category_ii = row.get('Category II', '')
            
         
            description = ''
            if self.use_description:
                description = row.get('Description', '')
            
       
            if pr_url and isinstance(pr_url, str):
                for url in pr_url.split('+'):
                    url = url.strip()
                    if url:
                        issue_data = {
                            'IssueTitle': issue_title,
                            'CategoryI': category_i,
                            'CategoryII': category_ii
                        }
                        
                    
                        if self.use_description:
                            issue_data['Description'] = description
                            
                        url_to_issue[self.normalize_url(url)] = issue_data
            
            if issue_url and isinstance(issue_url, str):
                for url in issue_url.split('+'):
                    url = url.strip()
                    if url:
                        issue_data = {
                            'IssueTitle': issue_title,
                            'CategoryI': category_i,
                            'CategoryII': category_ii
                        }
                        
                 
                        if self.use_description:
                            issue_data['Description'] = description
                            
                        url_to_issue[self.normalize_url(url)] = issue_data
        
   
        for idx, row in self.combined_data.iterrows():
            url = row.get('URL', '')
            if url:
                normalized_url = self.normalize_url(url)
                
           
                matched = False
                for key_url, issue_data in url_to_issue.items():
                    if key_url in normalized_url or normalized_url in key_url:
                        self.combined_data.at[idx, 'IssueTitle'] = issue_data['IssueTitle']
                        self.combined_data.at[idx, 'CategoryI'] = issue_data['CategoryI']
                        self.combined_data.at[idx, 'CategoryII'] = issue_data['CategoryII']
                        
            
                        if self.use_description and 'Description' in issue_data:
                            self.combined_data.at[idx, 'Description'] = issue_data['Description']
                            
                        matched = True
                        break
                
                if not matched:
                    print(f"No match found for URL: {url}")
        
        print(f"Matched URLs: {self.combined_data['IssueTitle'].notna().sum()} out of {len(self.combined_data)}")
    
    def normalize_url(self, url):
        
        if not url or not isinstance(url, str):
            return ""
        

        url = url.rstrip('/')
        

        if 'github.com' in url:

            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) >= 2:

                owner_repo = '/'.join(path_parts[:2])
                

                if len(path_parts) >= 4 and path_parts[2] in ['commit', 'pull']:
                    return f"github.com/{owner_repo}/{path_parts[2]}/{path_parts[3]}"
                
                return f"github.com/{owner_repo}"
        
  
        if 'issues.apache.org/jira' in url:
          
            if '/browse/' in url:
                issue_key = url.split('/browse/')[-1].split('#')[0].split('?')[0]
                return f"issues.apache.org/jira/browse/{issue_key}"
            
            if '/secure/attachment/' in url:
                attachment_id = url.split('/secure/attachment/')[-1].split('/')[0]
                return f"issues.apache.org/jira/secure/attachment/{attachment_id}"
        
        return url
    
    def prepare_prompts(self, batch_size=5):
        
        batches = []
        

        grouped_data = {}
        
  
        for _, row in self.combined_data.iterrows():
          
            before_content = row.get('BeforeContent', '')
            after_content = row.get('AfterContent', '')
            
            
            if (pd.isna(before_content) or before_content.strip() == '') and (pd.isna(after_content) or after_content.strip() == ''):
                print(f"Skipping entry without any code content: {row.get('IssueTitle', 'Unknown Issue')}")
                continue
                
            url = row.get('URL', '')
            if not url:
                url = "Unknown URL"  
                
           
            if '+' in url:
                urls = [u.strip() for u in url.split('+')]
            else:
                urls = [url]
                
            for single_url in urls:
                if single_url not in grouped_data:
                    grouped_data[single_url] = []
                    
                change = {
                    'URL': single_url,  
                    'Type': row.get('Type', ''),
                    'Owner': row.get('Owner', ''),
                    'Repo': row.get('Repo', ''),
                    'CommitSHA': row.get('CommitSHA', ''),
                    'PRNumber': row.get('PRNumber', ''),
                    'IssueKey': row.get('IssueKey', ''),
                    'Title': row.get('Title', ''),
                    'Message': row.get('Message', ''),
                    'Filename': row.get('Filename', ''),
                    'Status': row.get('Status', ''),
                    'BeforeContent': row.get('BeforeContent', '') if pd.notna(row.get('BeforeContent', '')) else '',  # May be missing
                    'AfterContent': row.get('AfterContent', '') if pd.notna(row.get('AfterContent', '')) else '',   # May be missing
                    'IssueTitle': row.get('IssueTitle', ''),
                    'CategoryI': row.get('CategoryI', ''),
                    'CategoryII': row.get('CategoryII', '')
                }
                
          
                if self.use_description and 'Description' in row and pd.notna(row['Description']):
                    change['Description'] = row.get('Description', '')
                grouped_data[single_url].append(change)
            
        print(f"Grouped data into {len(grouped_data)} unique URLs")
    
        total_issues = 0
        for url, changes in grouped_data.items():
            total_issues += len(changes)
            if len(changes) > 0:
                print(f"URL {url}: {len(changes)} changes, first issue: {changes[0].get('IssueTitle', 'Unknown')}")
        
        print(f"Total issues to process: {total_issues}")
        
 
        for url, changes in grouped_data.items():
          
            if len(changes) > batch_size:
                for i in range(0, len(changes), batch_size):
                    sub_batch = changes[i:i+batch_size]
                    prompt, token_count = self.create_prompt(sub_batch, changes[0].get('IssueTitle', ''))
                    batches.append({
                        'prompt': prompt,
                        'code_changes': sub_batch,
                        'url': url,
                        'issue_title': changes[0].get('IssueTitle', ''),
                        'token_usage': token_count
                    })
            else:
             
                prompt, token_count = self.create_prompt(changes, changes[0].get('IssueTitle', ''))
                batches.append({
                    'prompt': prompt,
                    'code_changes': changes,
                    'url': url,
                    'issue_title': changes[0].get('IssueTitle', ''),
                    'token_usage': token_count
                })
        
        print(f"Prepared {len(batches)} batches for LLM analysis")
        
     
        for i, batch in enumerate(batches):
            print(f"Batch {i+1}: {len(batch['code_changes'])} changes, Issue: {batch['issue_title']}, Estimated tokens: {batch['token_usage']}")
        
        return batches
    
    def get_category_pattern_explanations(self):
       
        category_explanations = {
            "IL": "Insecure Log Storage & Access Control - Logging code lacks proper security measures for log storage or access methods. This category focuses on issues with how logs are stored or configured, not the logged information itself.",
            "SS": "Sensitive Information Exposure - Logging code directly or indirectly record sensitive information, leading to security/privacy leaks. This category emphasizes the sensitivity of the logged information itself, not the storage method.",
            "RM": "Improper Redaction or Masking - Sensitive information in the logging code that should be masked is either not redacted or implemented with flaws. This category focuses on whether the code properly handles potentially sensitive information.",
            "EE": "Error & Exception Message Exposure - Sensitive data or system details are leaked through error messages or stack traces. This category specifically addresses sensitive information exposed through exception handling paths."
        }
        
        pattern_explanations = {
            "IL-At": "Risk of Log Injection Attacks - Log entries lack input filtering or escaping, allowing attackers to inject malicious content that could confuse audit trails or bypass security monitoring.",
            "IL-Pa": "Publicly Accessible Logs - Log files or output channels are publicly accessible, allowing any unauthorized user to directly access internal operational information.",
            "IL-UI": "Unauthorized Log Access - Logs lack proper access controls or have misconfigured permissions, allowing internal personnel or external users who shouldn't have access to view logs.",
            "IL-Lv": "Insecure Logging Level Configuration - Improper logging level configuration (e.g., debug mode left enabled) causes sensitive data or system details to be recorded in logs.",
            "SS-Cr": "Credentials Leakage - Logs record sensitive credentials like accounts, passwords, API keys, or OAuth tokens that could be directly stolen and used for attacks.",
            "SS-Cf": "Configuration Data Exposure - Log output includes database connection URLs, key file paths, environment variables, or other system configuration that attackers could use for further penetration.",
            "SS-Ur": "User Private Data Leakage - Logging code contain user cookies, usernames, phone numbers, transaction records, or other private data, creating compliance risks and privacy violations.",
            "RM-Ms": "Missing Masking/Redaction - Sensitive information in the logging code completely lacks masking or redaction, directly exposing original content in logs.",
            "RM-Ft": "Faulty Masking/Obfuscation - Redaction methods are implemented but flawed (e.g., partial hiding, reversible masking), logging code still may exposing some sensitive content.",
            "EE-Ex": "Exception Leakage - Exception message text contains keys, file paths, configuration parameters, or other sensitive information, allowing attackers to learn system internals.",
            "EE-St": "Stack Trace Leakage - Stack traces output to logs expose function call chains, internal class names, or library versions, providing system structure intelligence to attackers."
        }
        
        explanation_text = "CATEGORY AND PATTERN EXPLANATIONS:\n\nCategories:\n"
        for code, explanation in category_explanations.items():
            explanation_text += f"- {code}: {explanation}\n"
        
        explanation_text += "\nPatterns:\n"
        for code, explanation in pattern_explanations.items():
            explanation_text += f"- {code}: {explanation}\n"
        
        return explanation_text + "\n"
    
    def create_prompt(self, code_changes, issue_title=None):
        
      
        if "gpt-4" in self.model:
           
            if "32k" in self.model:
                MAX_MODEL_TOKENS = 32000
            elif "16k" in self.model:
                MAX_MODEL_TOKENS = 16000
            elif "turbo" in self.model or "o" in self.model:  
                MAX_MODEL_TOKENS = 128000  
            else:
                MAX_MODEL_TOKENS = 8000  
        elif "gpt-3.5" in self.model:
         
            if "16k" in self.model:
                MAX_MODEL_TOKENS = 16000
            else:
                MAX_MODEL_TOKENS = 4000 
        else:
          
            MAX_MODEL_TOKENS = 8000
        
      
        MAX_TOKENS = int(MAX_MODEL_TOKENS * 0.9)
        
        intro = """You are a security expert analyzing logging code for security vulnerabilities. Your task is to identify potential security issues in the provided code.

"""
        
        instructions = """INSTRUCTIONS:

1. Examine the BeforeContent to identify security issues.
2. Follow this two-step classification process:

   STEP 1 - Identify ONE CATEGORY:
   - IL: Insecure Log Storage & Access Control
   - SS: Sensitive Information Exposure
   - RM: Improper Redaction or Masking
   - EE: Error & Exception Message Exposure
   - NO: No Security Issue Found

   STEP 2 - Identify ONE PATTERN with category prefix:
   - IL-At: Risk of Log Injection Attacks
   - IL-Pa: Publicly Accessible Logs
   - IL-UI: Unauthorized Log Access
   - IL-Lv: Insecure Logging Level Configuration
   - SS-Cr: Credentials Leakage
   - SS-Cf: Configuration Data Exposure
   - SS-Ur: User private data Leakage
   - RM-Ms: Missing Masking/Redaction
   - RM-Ft: Faulty Masking/Obfuscation
   - EE-Ex: Exception Leakage
   - EE-St: Stack Trace Leakage

3. For each issue:
   - Describe the security concern
   - Explain why it's problematic
   - Provide specific recommendations for fixing
   - Include a complete fixed code snippet

IMPORTANT: YOU MUST FORMAT YOUR RESPONSE EXACTLY AS FOLLOWS:

URL: [URL of the code]
FILENAME: [Name of the file]
ISSUE_TITLE: [Title of the issue (if available)]
DESCRIPTION: [Brief description of the logging security issue]
CATEGORY: [Category code (IL, SS, RM, EE, or NO)]
PATTERN: [Pattern code without category prefix (e.g., At, Cr, Ms) - only if security issue found]
PROBLEM: [Explanation of why the code is problematic]
FIX_RECOMMENDATION: [Specific recommendations for fixing]
FIXED_CODE: [Complete fixed version of the code]
---END OF ANALYSIS---

CRITICAL REQUIREMENTS:
1. You MUST include ALL the sections listed above in your response.
2. You MUST end each analysis with ---END OF ANALYSIS--- as a separator between analyses.
3. For FIXED_CODE, provide the complete fixed code, not just changed parts.
4. If there are multiple issues, provide multiple analyses with the separator between them.
5. NEVER leave your response empty or incomplete.
6. ALWAYS include the ---END OF ANALYSIS--- marker at the end of your analysis.
"""
        
        code_intro = "Code Changes:\n"
        
     
        missing_content_note = ""
        for change in code_changes:
            before_content = change.get('BeforeContent', '').strip()
            after_content = change.get('AfterContent', '').strip()
            if not before_content and not after_content:
                missing_content_note = "\n\nNOTE: Some code changes may have missing BeforeContent or AfterContent. Analyze what is available and provide recommendations based on the issue description and context.\n"
                break
        
        if missing_content_note:
            code_intro += missing_content_note
        
      
        explanation_text = ""
        explanation_tokens = 0
        if self.use_explanation:
            explanation_text = self.get_category_pattern_explanations()
            explanation_tokens = estimate_tokens(explanation_text)
            print(f"Including detailed explanations of categories and patterns ({explanation_tokens} estimated tokens)")
            
        intro_tokens = estimate_tokens(intro)
        instructions_tokens = estimate_tokens(instructions)
        code_intro_tokens = estimate_tokens(code_intro)
        
     
        if code_changes:
        
            try:
                code_json = json.dumps(code_changes, indent=2)
                code_tokens = estimate_tokens(code_json)
            except Exception as e:
              
                print(f"Warning: Error estimating full code tokens: {e}. Using sampling method.")
                sample_size = min(3, len(code_changes))
                sample_json = json.dumps(code_changes[:sample_size], indent=2)
                tokens_per_change = estimate_tokens(sample_json) / sample_size
                code_tokens = int(tokens_per_change * len(code_changes))
        else:
            code_tokens = 0
        
    
        has_code_content = False
        for change in code_changes:
            before_content = change.get('BeforeContent', '').strip()
            after_content = change.get('AfterContent', '').strip()
            if before_content or after_content:
                has_code_content = True
                break
        
        if not has_code_content:
            print("Warning: No actual code content found in code changes")
       
            minimal_prompt = intro + instructions + code_intro + "[No code content available for analysis]"
            return minimal_prompt, estimate_tokens(minimal_prompt)
        
      
        essential_tokens = intro_tokens + instructions_tokens + explanation_tokens + code_intro_tokens + code_tokens
        
       
        if essential_tokens > MAX_TOKENS:
            print(f"Warning: Essential content exceeds token limit ({essential_tokens} > {MAX_TOKENS}).")
            print("Will truncate code to fit within token limit.")
            
           
            available_code_tokens = MAX_TOKENS - intro_tokens - instructions_tokens - explanation_tokens - code_intro_tokens
            
            if available_code_tokens <= 0:
                print("Warning: Very limited tokens available. Will try to include minimal code content.")
               
                if code_changes:
                    
                    simplified_changes = []
                    for change in code_changes[:1]:
                        simplified_change = {
                            'URL': change.get('URL', ''),
                            'Filename': change.get('Filename', ''),
                            'BeforeContent': change.get('BeforeContent', '')[:1000] + "..." if len(change.get('BeforeContent', '')) > 1000 else change.get('BeforeContent', ''),
                            'IssueTitle': change.get('IssueTitle', '')
                        }
                        simplified_changes.append(simplified_change)
                    
                    simplified_json = json.dumps(simplified_changes, indent=2)
                    code_tokens = estimate_tokens(simplified_json)
                    code_changes = simplified_changes
                    print(f"Created simplified code summary with {code_tokens} estimated tokens")
                else:
                    print("Error: No code changes available and no tokens for content!")
                    prompt = intro + instructions + code_intro + "[Code too large to include in prompt]"
                    return prompt, estimate_tokens(intro + instructions + code_intro + "[Code too large to include in prompt]")
   
            min_changes = 1
            for i in range(len(code_changes), min_changes - 1, -1):
                truncated_changes = code_changes[:i]
                truncated_json = json.dumps(truncated_changes, indent=2)
                if estimate_tokens(truncated_json) <= available_code_tokens:
                    code_changes = truncated_changes
                    code_tokens = estimate_tokens(truncated_json)
                    print(f"Code truncated to {i}/{len(code_changes)} changes to fit token limit")
                    break
                elif i == min_changes:
                    
                    print(f"Warning: Even single code change exceeds token limit. Forcing to keep first change.")
                    code_changes = code_changes[:min_changes]
                    code_tokens = estimate_tokens(json.dumps(code_changes, indent=2))
                    break
            
        
            essential_tokens = intro_tokens + instructions_tokens + explanation_tokens + code_intro_tokens + code_tokens
        
       
        available_tokens = MAX_TOKENS - essential_tokens
        
       
        prompt = intro
        
     
        if self.use_explanation and explanation_text:
            prompt += explanation_text
        
      
        title_tokens = 0
        if issue_title and issue_title != "Unknown Issue":
            title_context = f"CONTEXT: The code is related to an issue titled: \"{issue_title}\"\nThis provides context about the security problem being addressed.\n\n"
            title_tokens = estimate_tokens(title_context)
            
         
            if title_tokens <= available_tokens:
                prompt += title_context
                available_tokens -= title_tokens
            else:
                print(f"Warning: Issue title too long ({title_tokens} estimated tokens), skipping")
                title_tokens = 0  
       
        if self.use_description and code_changes and 'Description' in code_changes[0] and code_changes[0]['Description']:
            description = code_changes[0]['Description']
            
          
            desc_prefix = "ADDITIONAL CONTEXT: Here is a detailed description of the issue:\n"
            desc_suffix = "\nThis description provides additional insights about the security concern being addressed.\n\n"
            
        
            prefix_suffix_tokens = estimate_tokens(desc_prefix) + estimate_tokens(desc_suffix)
            
       
            desc_tokens = estimate_tokens(description)
            
          
            if desc_tokens + prefix_suffix_tokens > available_tokens:
               
                if available_tokens <= prefix_suffix_tokens:
                   
                    print(f"Warning: No space for description ({desc_tokens} estimated tokens), skipping")
                else:
                  
                    available_desc_tokens = available_tokens - prefix_suffix_tokens
                  
                    keep_ratio = available_desc_tokens / desc_tokens
               
                    keep_chars = int(len(description) * keep_ratio)
                    truncated_desc = description[:keep_chars] + "... [truncated due to token limit]"
                    
                    print(f"Description truncated to approximately {keep_ratio:.1%} of original length to avoid token limit")
                    prompt += desc_prefix + truncated_desc + desc_suffix
            else:
               
                prompt += desc_prefix + description + desc_suffix
        
      
        prompt += instructions + code_intro
        
       
        if code_changes:
            prompt += json.dumps(code_changes, indent=2)
            print(f"Added {len(code_changes)} code changes to prompt")
        else:
            prompt += "[No code changes available]"
            print("Warning: No code changes available for prompt")
        
       
        total_tokens = estimate_tokens(prompt)
        
        return prompt, total_tokens
    
    def analyze_with_llm(self, batches):
        
        print("Starting LLM analysis...")
        
        if not self.api_key:
            print("WARNING: No API key provided. Skipping LLM analysis.")
            print("Sample prompt for manual analysis:")
            if batches:
                print(batches[0]['prompt'][:500] + "...\n(truncated)")
            return
        
      
        if not self.client:
            self.client = OpenAI(api_key=self.api_key)
            
            
            if self.api_url and 'openai.com' not in self.api_url:
                self.client.base_url = self.api_url
        
        results = []
        
        for i, batch in enumerate(batches):
            print(f"Processing batch {i+1}/{len(batches)}")
            
            try:
               
                if "gpt-5" in self.model:
                  
                    system_prompt = """You are an expert in analyzing code for logging security issues.
                    
IMPORTANT: You MUST respond using the exact format specified in the user's prompt. 
Always include the required sections: URL, FILENAME, ISSUE_TITLE, DESCRIPTION, CATEGORY, PATTERN, PROBLEM, FIX_RECOMMENDATION, FIXED_CODE.
Always end each analysis with ---END OF ANALYSIS--- marker.
Never leave any response blank or incomplete."""
                    
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": batch['prompt']}
                        ],
                        max_completion_tokens=2048,  
                        temperature=1,  
                        frequency_penalty=0.0,
                        presence_penalty=0.0
                    )
                elif "nano" in self.model or "1-nano" in self.model:
                  
                    system_prompt = """You are an expert in analyzing code for logging security issues.
                    
IMPORTANT: You MUST respond using the exact format specified in the user's prompt. 
Always include the required sections: URL, FILENAME, ISSUE_TITLE, DESCRIPTION, CATEGORY, PATTERN, PROBLEM, FIX_RECOMMENDATION, FIXED_CODE.
Always end each analysis with ---END OF ANALYSIS--- marker.
Never leave any response blank or incomplete."""
                    
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": batch['prompt']}
                        ],
                        max_tokens=2048, 
                        temperature=1,
                        frequency_penalty=0.0,
                        presence_penalty=0.0
                      
                    )
                else:
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": "You are an expert in analyzing code for logging security issues."},
                            {"role": "user", "content": batch['prompt']}
                        ],
                        max_tokens=2048, 
                        temperature=1, 
                        top_p=0.95,       
                        frequency_penalty=0.0,
                        presence_penalty=0.0
                    )
                
                
                try:
                    
                    llm_response = response.choices[0].message.content
                    
                  
                    token_usage_info = {}
                    if hasattr(response, 'usage') and response.usage:
                        token_usage_info = {
                            'input_tokens': getattr(response.usage, 'prompt_tokens', 0),
                            'output_tokens': getattr(response.usage, 'completion_tokens', 0),
                            'total_tokens': getattr(response.usage, 'total_tokens', 0)
                        }
                        print(f"Token usage for batch {i+1}: Input={token_usage_info['input_tokens']}, Output={token_usage_info['output_tokens']}, Total={token_usage_info['total_tokens']}")
                    else:
                        token_usage_info = {
                            'input_tokens': batch.get('token_usage', 0), 
                            'output_tokens': 'Not available',
                            'total_tokens': 'Not available'
                        }
                        print(f"Token usage not available for batch {i+1}, using estimated input tokens: {token_usage_info['input_tokens']}")
                    
                
                    if not llm_response or llm_response.strip() == "":
                        print(f"Warning: Empty response received from batch {i+1}")
                        
                        if 'issue_title' in batch:
                            fallback_results = [{
                                'url': batch.get('url', ''),
                                'filename': '',
                                'issue_title': batch.get('issue_title', 'Unknown Issue'),
                                'description': 'No analysis provided by LLM (empty response)',
                                'category': 'NO', 
                                'pattern': '',
                                'problem': 'LLM returned empty response',
                                'fix_recommendation': 'Try with different model or smaller batch size',
                                'fixed_code': '',
                                'input_tokens': token_usage_info['input_tokens'],
                                'output_tokens': token_usage_info['output_tokens'],
                                'total_tokens': token_usage_info['total_tokens']
                            }]
                            results.extend(fallback_results)
                            print(f"Added fallback result for batch {i+1}")
                            continue
                    
                   
                    if "gpt-5" in self.model and '---END OF ANALYSIS---' not in llm_response:
                        print(f"Warning: GPT-5 Nano response missing format markers in batch {i+1}")
                        
                        llm_response = llm_response + "\n---END OF ANALYSIS---"
                    
                  
                    print(f"Full LLM response from batch {i+1}:")
                    print(llm_response)
                    
                 
                    parsed_results = self.parse_text_response(llm_response, batch['issue_title'])
                    if parsed_results:
                       
                        for result in parsed_results:
                            result['input_tokens'] = token_usage_info['input_tokens']
                            result['output_tokens'] = token_usage_info['output_tokens']
                            result['total_tokens'] = token_usage_info['total_tokens']
                        results.extend(parsed_results)
                        print(f"Successfully parsed {len(parsed_results)} results from batch {i+1}")
                    else:
                        print(f"Could not parse any results from LLM response in batch {i+1}")
                        print(f"Response preview: {llm_response[:200]}...")
                        
                       
                        if 'issue_title' in batch:
                            fallback_results = [{
                                'url': batch.get('url', ''),
                                'filename': '',
                                'issue_title': batch.get('issue_title', 'Unknown Issue'),
                                'description': 'Failed to parse LLM response',
                                'category': 'NO',  
                                'pattern': '',
                                'problem': 'LLM response could not be parsed',
                                'fix_recommendation': 'Try with different model or smaller batch size',
                                'fixed_code': '',
                                'input_tokens': token_usage_info['input_tokens'],
                                'output_tokens': token_usage_info['output_tokens'],
                                'total_tokens': token_usage_info['total_tokens']
                            }]
                            results.extend(fallback_results)
                            print(f"Added fallback result for batch {i+1}")
                except Exception as e:
                    print(f"Error parsing LLM response in batch {i+1}: {e}")
                    
                    
                    if 'issue_title' in batch:
                        fallback_results = [{
                            'url': batch.get('url', ''),
                            'filename': '',
                            'issue_title': batch.get('issue_title', 'Unknown Issue'),
                            'description': f'Error parsing LLM response: {str(e)}',
                            'category': 'NO',  
                            'pattern': '',
                            'problem': 'Exception during response parsing',
                            'fix_recommendation': 'Try with different model or smaller batch size',
                            'fixed_code': '',
                            'input_tokens': batch.get('token_usage', 'Not available'),
                            'output_tokens': 'Not available',
                            'total_tokens': 'Not available'
                        }]
                        results.extend(fallback_results)
                        print(f"Added fallback result for batch {i+1} due to exception")
                
                
                time.sleep(2)
                
            except Exception as e:
                print(f"Exception in batch {i+1}: {e}")
                print(f"Error details: {str(e)}")
              
                if "rate limit" in str(e).lower() or "timeout" in str(e).lower():
                    print("Rate limit or timeout encountered. Waiting 30 seconds before retrying...")
                    time.sleep(30)
                    try:
                   
                        if "gpt-5" in self.model:
                         
                            system_prompt = """You are an expert in analyzing code for logging security issues.
                            
IMPORTANT: You MUST respond using the exact format specified in the user's prompt. 
Always include the required sections: URL, FILENAME, ISSUE_TITLE, DESCRIPTION, CATEGORY, PATTERN, PROBLEM, FIX_RECOMMENDATION, FIXED_CODE.
Always end each analysis with ---END OF ANALYSIS--- marker.
Never leave any response blank or incomplete."""
                            
                            response = self.client.chat.completions.create(
                                model=self.model,
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": batch['prompt']}
                                ],
                                max_completion_tokens=2048, 
                                temperature=1 
                            )
                        elif "nano" in self.model or "1-nano" in self.model:
                          
                            system_prompt = """You are an expert in analyzing code for logging security issues.
                            
IMPORTANT: You MUST respond using the exact format specified in the user's prompt. 
Always include the required sections: URL, FILENAME, ISSUE_TITLE, DESCRIPTION, CATEGORY, PATTERN, PROBLEM, FIX_RECOMMENDATION, FIXED_CODE.
Always end each analysis with ---END OF ANALYSIS--- marker.
Never leave any response blank or incomplete."""
                            
                            response = self.client.chat.completions.create(
                                model=self.model,
                                messages=[
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": batch['prompt']}
                                ],
                                max_tokens=2048,
                                temperature=1
                            )
                        else:
                            response = self.client.chat.completions.create(
                                model=self.model,
                                messages=[
                                    {"role": "system", "content": "You are an expert in analyzing code for logging security issues."},
                                    {"role": "user", "content": batch['prompt']}
                                ],
                                max_tokens=2048,
                                temperature=1,
                                top_p=0.95
                            )
                        llm_response = response.choices[0].message.content
                        
                       
                        retry_token_usage_info = {}
                        if hasattr(response, 'usage') and response.usage:
                            retry_token_usage_info = {
                                'input_tokens': getattr(response.usage, 'prompt_tokens', 0),
                                'output_tokens': getattr(response.usage, 'completion_tokens', 0),
                                'total_tokens': getattr(response.usage, 'total_tokens', 0)
                            }
                            print(f"Retry token usage for batch {i+1}: Input={retry_token_usage_info['input_tokens']}, Output={retry_token_usage_info['output_tokens']}, Total={retry_token_usage_info['total_tokens']}")
                        else:
                            retry_token_usage_info = {
                                'input_tokens': batch.get('token_usage', 'Not available'),
                                'output_tokens': 'Not available',
                                'total_tokens': 'Not available'
                            }
                        
                        
                        if "gpt-5" in self.model and '---END OF ANALYSIS---' not in llm_response:
                            print(f"Warning: GPT-5 Nano retry response missing format markers in batch {i+1}")
                            
                            llm_response = llm_response + "\n---END OF ANALYSIS---"
                        
                        parsed_results = self.parse_text_response(llm_response, batch['issue_title'])
                        if parsed_results:
                         
                            for result in parsed_results:
                                result['input_tokens'] = retry_token_usage_info['input_tokens']
                                result['output_tokens'] = retry_token_usage_info['output_tokens']
                                result['total_tokens'] = retry_token_usage_info['total_tokens']
                            results.extend(parsed_results)
                            print(f"Successfully parsed {len(parsed_results)} results from retry of batch {i+1}")
                        else:
                      
                            if 'issue_title' in batch:
                                fallback_results = [{
                                    'url': batch.get('url', ''),
                                    'filename': '',
                                    'issue_title': batch.get('issue_title', 'Unknown Issue'),
                                    'description': 'Failed to parse LLM response on retry',
                                    'category': 'NO', 
                                    'pattern': '',
                                    'problem': 'LLM retry response could not be parsed',
                                    'fix_recommendation': 'Try with different model or smaller batch size',
                                    'fixed_code': '',
                                    'input_tokens': retry_token_usage_info['input_tokens'],
                                    'output_tokens': retry_token_usage_info['output_tokens'],
                                    'total_tokens': retry_token_usage_info['total_tokens']
                                }]
                                results.extend(fallback_results)
                                print(f"Added fallback result for retry of batch {i+1}")
                    except Exception as retry_error:
                        print(f"Retry also failed for batch {i+1}: {retry_error}")
                   
                        if 'issue_title' in batch:
                            fallback_results = [{
                                'url': batch.get('url', ''),
                                'filename': '',
                                'issue_title': batch.get('issue_title', 'Unknown Issue'),
                                'description': f'Retry failed: {str(retry_error)}',
                                'category': 'NO', 
                                'pattern': '',
                                'problem': 'API error on retry',
                                'fix_recommendation': 'Try with different model or smaller batch size',
                                'fixed_code': '',
                                'input_tokens': batch.get('token_usage', 'Not available'),
                                'output_tokens': 'Not available',
                                'total_tokens': 'Not available'
                            }]
                            results.extend(fallback_results)
                            print(f"Added fallback result for failed retry of batch {i+1}")
                else:
                 
                    if 'issue_title' in batch:
                        fallback_results = [{
                            'url': batch.get('url', ''),
                            'filename': '',
                            'issue_title': batch.get('issue_title', 'Unknown Issue'),
                            'description': f'API error: {str(e)}',
                            'category': 'NO', 
                            'pattern': '',
                            'problem': 'API error occurred',
                            'fix_recommendation': 'Try with different model or smaller batch size',
                            'fixed_code': '',
                            'input_tokens': batch.get('token_usage', 'Not available'),
                            'output_tokens': 'Not available',
                            'total_tokens': 'Not available'
                        }]
                        results.extend(fallback_results)
                        print(f"Added fallback result for batch {i+1} due to API error")
        
        self.output_data = results
        print(f"Completed LLM analysis with {len(results)} results")
    
    def parse_text_response(self, text, original_issue_title=None):
       
        results = []
        
    
        if not text or text.strip() == "":
            print("Warning: Received empty response from LLM")
       
            if original_issue_title:
                results.append({
                    'url': '',
                    'filename': '',
                    'issue_title': original_issue_title,
                    'description': 'No analysis provided by LLM (empty response)',
                    'category': 'NO',  
                    'pattern': '',
                    'problem': 'LLM returned empty response',
                    'fix_recommendation': 'Try with different model or smaller batch size',
                    'fixed_code': '',
                    'input_tokens': 'Not available',
                    'output_tokens': 'Not available',
                    'total_tokens': 'Not available'
                })
            return results
        
       
        analyses = text.split('---END OF ANALYSIS---')
        
        for analysis in analyses:
            if not analysis.strip():
                continue
                
           
            import re
            
          
            if original_issue_title:
                issue_title = original_issue_title
            else:
                issue_title_match = re.search(r'ISSUE_TITLE:\s*(.*?)(?:\n|$)', analysis)
                issue_title = issue_title_match.group(1).strip() if issue_title_match else ""
            
   
            description_match = re.search(r'DESCRIPTION:\s*(.*?)(?:\n(?:[A-Z_]+:|$))', analysis, re.DOTALL)
            description = description_match.group(1).strip() if description_match else ""
        
            category_match = re.search(r'CATEGORY:\s*(.*?)(?:\n|$)', analysis)
            category = category_match.group(1).strip() if category_match else ""
        
            category = category.strip('[]')
       
            category = category.strip('"\'')
        
            if ' ' in category and len(category) > 2:
              
                code_match = re.match(r'([A-Z]{2})\s*[-:]\s*.*', category)
                if code_match:
                    category = code_match.group(1)
         
            pattern_match = re.search(r'PATTERN:\s*(.*?)(?:\n|$)', analysis)
            pattern = pattern_match.group(1).strip() if pattern_match else ""
          
            pattern = pattern.strip('[]')
          
            pattern = pattern.strip('"\'')
            
          
            if pattern:
                
                if re.match(r'^[A-Z]{2}-[A-Za-z]{2}$', pattern):
                  
                    pass
                    
                
                elif ' ' in pattern:
                   
                    code_match = re.match(r'([A-Z]{2}-[A-Za-z]{2})\s*[-:]\s*.*', pattern)
                    if code_match:
                        pattern = code_match.group(1)
                    else:
                      
                        code_match = re.match(r'([A-Za-z]{2})\s*[-:(].*', pattern)
                        if code_match and category:
                            pattern_code = code_match.group(1)
                            
                            valid_patterns = {
                                "IL": ["At", "Pa", "UI", "Lv"],
                                "SS": ["Cr", "Cf", "Ur"],
                                "RM": ["Ms", "Ft"],
                                "EE": ["Ex", "St"]
                            }
                            if category in valid_patterns and pattern_code in valid_patterns[category]:
                                pattern = f"{category}-{pattern_code}"
                
             
                elif len(pattern) == 2 and category:
                   
                    valid_patterns = {
                        "IL": ["At", "Pa", "UI", "Lv"],
                        "SS": ["Cr", "Cf", "Ur"],
                        "RM": ["Ms", "Ft"],
                        "EE": ["Ex", "St"]
                    }
                    if category in valid_patterns and pattern in valid_patterns[category]:
                        pattern = f"{category}-{pattern}"
            
     
            problem_match = re.search(r'PROBLEM:\s*(.*?)(?:\n(?:[A-Z_]+:|$))', analysis, re.DOTALL)
            problem = problem_match.group(1).strip() if problem_match else ""
            
          
            fix_match = re.search(r'FIX_RECOMMENDATION:\s*(.*?)(?:\n(?:URL:|FIXED_CODE:|[A-Z_]+:|$))', analysis, re.DOTALL)
            fix_recommendation = fix_match.group(1).strip() if fix_match else "No specific fix recommendation provided."
         
            has_code_samples = '---END OF CODE SAMPLE---' in analysis
            
          
            code_samples = []
            if has_code_samples:
                code_samples = re.split(r'---END OF CODE SAMPLE---', analysis)
               
                if len(code_samples) > 1:
                    code_samples = code_samples[1:]  
            
         
            if not has_code_samples:
              
                url_sections = re.finditer(r'URL:\s*(.*?)(?:\n|$)(.*?)(?=URL:|$)', analysis, re.DOTALL)
                
                url_found = False
                for match in url_sections:
                    url_found = True
                    url = match.group(1).strip()
                    section_text = match.group(2)
                    
                  
                    result = {
                        'url': url,
                        'filename': '',
                        'issue_title': issue_title,
                        'description': description,
                        'category': category,
                        'pattern': pattern,
                        'problem': problem,
                        'fix_recommendation': fix_recommendation,
                        'fixed_code': '',
                        'input_tokens': 'Not available',
                        'output_tokens': 'Not available',
                        'total_tokens': 'Not available'
                    }
                    
                  
                    filename_match = re.search(r'FILENAME:\s*(.*?)(?:\n|$)', section_text)
                    if filename_match:
                        result['filename'] = filename_match.group(1).strip()
                    
              
                    result['fixed_code'] = self._extract_fixed_code(section_text, "FIXED_CODE")
                    
          
                    if result['url'] or result['filename'] or result['description']:
                  
                        fixed_code_length = len(result['fixed_code']) if result['fixed_code'] else 0
                        print(f"Extracted fixed code for {result['filename']}: {fixed_code_length} characters")
                        results.append(result)
                
        
                if not url_found:
                    result = {
                        'url': '',
                        'filename': '',
                        'issue_title': issue_title,
                        'description': description,
                        'category': category,
                        'pattern': pattern,
                        'problem': problem,
                        'fix_recommendation': fix_recommendation,
                        'fixed_code': '',
                        'input_tokens': 'Not available',
                        'output_tokens': 'Not available',
                        'total_tokens': 'Not available'
                    }
                    
                 
                    url_match = re.search(r'URL:\s*(.*?)(?:\n|$)', analysis)
                    if url_match:
                        result['url'] = url_match.group(1).strip()
                        
                    filename_match = re.search(r'FILENAME:\s*(.*?)(?:\n|$)', analysis)
                    if filename_match:
                        result['filename'] = filename_match.group(1).strip()
                        
                    result['fixed_code'] = self._extract_fixed_code(analysis, "FIXED_CODE")
                    
              
                    if result['issue_title'] or result['description'] or result['category']:
                        results.append(result)
            else:
             
                for sample in code_samples:
                    if not sample.strip():
                        continue
                        
               
                    result = {
                        'url': '',
                        'filename': '',
                        'issue_title': issue_title,
                        'description': description,
                        'category': category,
                        'pattern': pattern,
                        'problem': problem,
                        'fix_recommendation': fix_recommendation,
                        'fixed_code': '',
                        'input_tokens': 'Not available',
                        'output_tokens': 'Not available',
                        'total_tokens': 'Not available'
                    }
                    
                
                    url_match = re.search(r'URL:\s*(.*?)(?:\n|$)', sample)
                    if url_match:
                        result['url'] = url_match.group(1).strip()
                        
                
                    filename_match = re.search(r'FILENAME:\s*(.*?)(?:\n|$)', sample)
                    if filename_match:
                        result['filename'] = filename_match.group(1).strip()
                        
            
                    result['fixed_code'] = self._extract_fixed_code(sample, "FIXED_CODE")
                    
                  
                    if result['url'] or result['filename'] or result['description']:
                 
                        fixed_code_length = len(result['fixed_code']) if result['fixed_code'] else 0
                        print(f"Extracted fixed code for {result['filename']}: {fixed_code_length} characters")
                        results.append(result)
            
       
            if not any(r.get('issue_title') == issue_title for r in results) and issue_title:
                results.append({
                    'url': '',
                    'filename': '',
                    'issue_title': issue_title,
                    'description': description,
                    'category': category,
                    'pattern': pattern,
                    'problem': problem,
                    'fix_recommendation': fix_recommendation,
                    'fixed_code': '',
                    'input_tokens': 'Not available',
                    'output_tokens': 'Not available',
                    'total_tokens': 'Not available'
                })
        
     
        if not results and original_issue_title:
            results.append({
                'url': '',
                'filename': '',
                'issue_title': original_issue_title,
                'description': 'Failed to parse LLM response',
                'category': 'NO', 
                'pattern': '',
                'problem': 'LLM response did not match expected format',
                'fix_recommendation': 'Try with different model or smaller batch size',
                'fixed_code': '',
                'input_tokens': 'Not available',
                'output_tokens': 'Not available',
                'total_tokens': 'Not available'
            })
            
        return results
    
    def _extract_fixed_code(self, text, section_name="FIXED_CODE"):
        
   
        pattern1 = rf'{section_name}:(?:\s*```(?:\w+)?\s*)?(.*?)(?=\n(?:[A-Z_]+:|$)|$)'
        match1 = re.search(pattern1, text, re.DOTALL)
        
        if match1:
            fixed_code = match1.group(1).strip()
          
            if fixed_code.endswith('```'):
                fixed_code = fixed_code[:-3].strip()
           
            if fixed_code.startswith('```'):
                lines = fixed_code.split('\n')
                if len(lines) > 1:
                   
                    if re.match(r'^```\w*$', lines[0]):
                        lines = lines[1:]
                    fixed_code = '\n'.join(lines).strip()
                    if fixed_code.endswith('```'):
                        fixed_code = fixed_code[:-3].strip()
            
          
            if fixed_code and len(fixed_code.strip()) > 10:  
                return fixed_code
        

        pattern2 = rf'{section_name}:\s*(```(?:\w+)?\s*\n(.*?)\n```)'
        match2 = re.search(pattern2, text, re.DOTALL)
        
        if match2:
            code_block = match2.group(2).strip()
            if code_block and len(code_block.strip()) > 10:
                return code_block
        
      
        pattern3 = rf'{section_name}:\s*(.*?)(?=\n(?:[A-Z_]+:|$))'
        match3 = re.search(pattern3, text, re.DOTALL)
        
        if match3:
            fixed_code = match3.group(1).strip()
            if fixed_code and len(fixed_code.strip()) > 10:
                return fixed_code
        
        return "No fixed code provided."
    
    def save_results(self, output_path):
      
        if not self.output_data:
            print("No results to save")
            return
        
    
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
       
        fieldnames = [
            'url', 'filename', 'issue_title', 'description', 'category', 'pattern',
            'problem', 'fix_recommendation', 'fixed_code', 'input_tokens', 'output_tokens', 'total_tokens', 'analysis_status'
        ]
        
     
        grouped_results = {}
        for result in self.output_data:
            issue_title = result.get('issue_title', 'Unknown Issue')
            if issue_title not in grouped_results:
                grouped_results[issue_title] = {
                    'url': [],
                    'filename': [],
                    'issue_title': issue_title,
                    'description': result.get('description', ''),
                    'category': result.get('category', ''),
                    'pattern': result.get('pattern', ''),
                    'problem': result.get('problem', ''),
                    'fix_recommendation': result.get('fix_recommendation', ''),
                    'fixed_code': [],
                    'input_tokens': result.get('input_tokens', 'Not available'),
                    'output_tokens': result.get('output_tokens', 'Not available'),
                    'total_tokens': result.get('total_tokens', 'Not available'),
                    'analysis_status': result.get('analysis_status', 'ANALYZED')  
                }
            
        
            url = result.get('url', '')
            if url and url not in grouped_results[issue_title]['url']:
                grouped_results[issue_title]['url'].append(url)
            
       
            filename = result.get('filename', '')
            if filename and filename not in grouped_results[issue_title]['filename']:
                grouped_results[issue_title]['filename'].append(filename)
        
            fixed_code = result.get('fixed_code', '')
            if fixed_code and fixed_code != "No fixed code provided.":
                prefix = f"[{filename}] " if filename else ""
                grouped_results[issue_title]['fixed_code'].append(f"{prefix}{fixed_code}")
        
      
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for issue_title, merged_result in grouped_results.items():
           
                merged_result['url'] = ' + '.join(merged_result['url'])
                merged_result['filename'] = ' + '.join(merged_result['filename'])
                
           
                fixed_codes = merged_result['fixed_code']
                cleaned_fixed_codes = []
                for code in fixed_codes:
                    if code and code != "No fixed code provided.":
                       
                        cleaned_code = code.replace('\n', '\\n').replace('\r', '\\r')
                        cleaned_fixed_codes.append(cleaned_code)
                    else:
                        cleaned_fixed_codes.append(code)
                
                merged_result['fixed_code'] = '\n\n---\n\n'.join(cleaned_fixed_codes)
                
           
                final_fixed_code_length = len(merged_result['fixed_code'])
                print(f"Final fixed_code for {issue_title}: {final_fixed_code_length} characters")
                
                writer.writerow({
                    field: merged_result.get(field, '') for field in fieldnames
                })
        
        print(f"Results saved to {output_path}")
    
    def _validate_data_integrity(self):
        
        print("\n=== Data Integrity Validation ===")
        
      
        total_combined = len(self.combined_data)
        with_before_content = self.combined_data['BeforeContent'].notna().sum()
        with_after_content = self.combined_data['AfterContent'].notna().sum()
        with_url = self.combined_data['URL'].notna().sum()
        
        print(f"Combined data entries: {total_combined}")
        print(f"Entries with BeforeContent: {with_before_content}")
        print(f"Entries with AfterContent: {with_after_content}")
        print(f"Entries with URL: {with_url}")
        
    
        missing_both = self.combined_data[
            (self.combined_data['BeforeContent'].isna() | (self.combined_data['BeforeContent'] == '')) &
            (self.combined_data['AfterContent'].isna() | (self.combined_data['AfterContent'] == ''))
        ]
        
        if len(missing_both) > 0:
            print(f"\nWarning: {len(missing_both)} entries missing both BeforeContent and AfterContent:")
            for idx, row in missing_both.head(3).iterrows():
                print(f"  - Row {idx}: {row.get('IssueTitle', 'Unknown')} | URL: {row.get('URL', 'None')}")
            if len(missing_both) > 3:
                print(f"  ... and {len(missing_both) - 3} more")
        
       
        only_before = self.combined_data[
            (self.combined_data['BeforeContent'].notna() & (self.combined_data['BeforeContent'] != '')) &
            (self.combined_data['AfterContent'].isna() | (self.combined_data['AfterContent'] == ''))
        ]
        print(f"Entries with only BeforeContent: {len(only_before)}")
        
    
        only_after = self.combined_data[
            (self.combined_data['BeforeContent'].isna() | (self.combined_data['BeforeContent'] == '')) &
            (self.combined_data['AfterContent'].notna() & (self.combined_data['AfterContent'] != ''))
        ]
        print(f"Entries with only AfterContent: {len(only_after)}")
        
    
        both_content = self.combined_data[
            (self.combined_data['BeforeContent'].notna() & (self.combined_data['BeforeContent'] != '')) &
            (self.combined_data['AfterContent'].notna() & (self.combined_data['AfterContent'] != ''))
        ]
        print(f"Entries with both BeforeContent and AfterContent: {len(both_content)}")
        
        total_overview = len(self.overview_data)
        with_issue_title = self.overview_data['Issue Title'].notna().sum()
        
        print(f"\nOverview data entries: {total_overview}")
        print(f"Entries with Issue Title: {with_issue_title}")
        
        print("=== End Validation ===\n")
    
    def run_analysis(self, output_path, prompt_only=False):
        
  
        self.load_data()
        
    
        self.match_urls()
        
      
        all_issue_titles = set()
        for _, row in self.overview_data.iterrows():
            issue_title = row.get('Issue Title', '')
            if issue_title:
                all_issue_titles.add(issue_title)
        print(f"Found {len(all_issue_titles)} unique issue titles in overview data")
        
    
        batches = self.prepare_prompts(batch_size=self.batch_size)
        
        if prompt_only:
         
            if batches:
                sample_prompt_path = os.path.join(os.path.dirname(output_path), "sample_prompt.txt")
                with open(sample_prompt_path, 'w', encoding='utf-8') as f:
                    f.write(batches[0]['prompt'])
                print(f"Sample prompt saved to {sample_prompt_path}")
            return
        
   
        self.analyze_with_llm(batches)
        
  
        analyzed_issue_titles = set()
        for result in self.output_data:
            issue_title = result.get('issue_title', '')
            if issue_title:
                analyzed_issue_titles.add(issue_title)
        
        missing_issue_titles = all_issue_titles - analyzed_issue_titles
        if missing_issue_titles:
            print(f"Warning: {len(missing_issue_titles)} issue titles were not analyzed by LLM")
            print("Adding fallback results for missing issue titles...")
    
            for issue_title in missing_issue_titles:
                self.output_data.append({
                    'url': '',
                    'filename': '',
                    'issue_title': issue_title,
                    'description': 'Issue was not analyzed by LLM',
                    'category': 'NO',  
                    'pattern': '',
                    'problem': 'Issue was skipped during analysis, possibly due to token limits or missing code changes',
                    'fix_recommendation': 'Try running with a larger context model like gpt-4o or reducing batch size',
                    'fixed_code': '',
                    'input_tokens': 'Not available',
                    'output_tokens': 'Not available',
                    'total_tokens': 'Not available',
                    'analysis_status': 'MISSING' 
                })
            
            print(f"Added fallback results for {len(missing_issue_titles)} missing issue titles")
        
 
        self.save_results(output_path)


def main():
    parser = argparse.ArgumentParser(description='Analyze logging security issues using LLM')
    parser.add_argument('--combined-csv', required=True, help='Path to the combined_result.csv file')
    parser.add_argument('--overview-csv', required=True, help='Path to the Logging Security Overview CSV file')
    parser.add_argument('--output', required=True, help='Path to save the output CSV file')
    parser.add_argument('--api-key', help='API key for the LLM service')
    parser.add_argument('--api-url', default=None, 
                        help='URL endpoint for the LLM service (default: OpenAI standard API URL)')
    parser.add_argument('--model', default='gpt-4o-mini', 
                        help='Model name for OpenAI API (default: gpt-4o-mini, use "gpt-5-nano" for GPT-5 Nano)')
    parser.add_argument('--prompt-only', action='store_true', help='Generate prompts only without calling the LLM')
    parser.add_argument('--batch-size', type=int, default=10, 
                        help='Number of code changes to include in each batch (default: 10)')
    parser.add_argument('--temperature', type=float, default=1,
                        help='Temperature setting for the LLM (default: 1)')
    parser.add_argument('--max-retries', type=int, default=3,
                        help='Maximum number of retries for failed API calls (default: 3)')
    parser.add_argument('--use-description', action='store_true',
                        help='Include Description column from overview CSV as a hint for the LLM')
    parser.add_argument('--use-explanation', action='store_true',
                        help='Include detailed explanations of categories and patterns')
    
    args = parser.parse_args()
    
    analyzer = LogSecurityAnalyzer(
        args.combined_csv,
        args.overview_csv,
        args.api_key,
        args.api_url,
        args.model,
        args.batch_size,
        args.use_description,
        args.use_explanation
    )
    
    analyzer.run_analysis(args.output, args.prompt_only)


if __name__ == "__main__":
    main()

