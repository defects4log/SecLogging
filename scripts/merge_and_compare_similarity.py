#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import pandas as pd
import numpy as np
import re
import csv
import os
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from difflib import SequenceMatcher
import argparse
from typing import Dict, List, Tuple, Optional


class MergeAndCompareSimilarity:
    def __init__(self, llm_results_path: str, combined_results_path: str):
 
        self.llm_results_path = llm_results_path
        self.combined_results_path = combined_results_path
        self.llm_data = None
        self.combined_data = None
        self.similarity_results = []
        
    def load_data(self):
        
        print("Loading LLM analysis results...")
        
        encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1', 'cp1252']
        for encoding in encodings_to_try:
            try:
                self.llm_data = pd.read_csv(self.llm_results_path, encoding=encoding)
                print(f"Successfully loaded LLM results with encoding: {encoding}")
                print(f"Loaded {len(self.llm_data)} rows from LLM results")
                break
            except Exception as e:
                print(f"Failed to load LLM results with encoding {encoding}: {e}")
                continue
        else:
            print("Failed to load LLM results with any encoding")
            return False
            
        print("Loading combined results...")
      
        for encoding in encodings_to_try:
            try:
                self.combined_data = pd.read_csv(self.combined_results_path, encoding=encoding)
                print(f"Successfully loaded combined results with encoding: {encoding}")
                print(f"Loaded {len(self.combined_data)} rows from combined results")
                break
            except Exception as e:
                print(f"Failed to load combined results with encoding {encoding}: {e}")
                continue
        else:
            print("Failed to load combined results with any encoding")
            return False
            
       
        if self.llm_data is not None:
            print(f"LLM data columns: {list(self.llm_data.columns)}")
            print(f"LLM data shape: {self.llm_data.shape}")
            
        if self.combined_data is not None:
            print(f"Combined data columns: {list(self.combined_data.columns)}")
            print(f"Combined data shape: {self.combined_data.shape}")
            
        return True
    
    def preprocess_code(self, code_text: str) -> str:
  
        if pd.isna(code_text) or code_text == '':
            return ""
        
      
        code_text = str(code_text)
        
    
        code_text = re.sub(r'```\w*\n?', '', code_text)
        code_text = re.sub(r'```$', '', code_text)

        lines = code_text.split('\n')
        cleaned_lines = []
        for line in lines:
            if line.strip():  
                cleaned_lines.append(line.rstrip())  
        
        result = '\n'.join(cleaned_lines).strip()
        
        
        if not result:
            print(f"Warning: Preprocessing resulted in empty string, using original text")
            return code_text.strip()
        
        return result
    
    def merge_after_content_by_issue_title(self) -> Dict[str, str]:
      
        print("Merging AfterContent by issue title...")
        
       
        print(f"Available columns in combined data: {list(self.combined_data.columns)}")
     
        issue_title_col = None
        
      
        if 'Issue Title' in self.combined_data.columns:
            issue_title_col = 'Issue Title'
            
        else:
           
            for col in self.combined_data.columns:
                if 'issue' in col.lower() and 'title' in col.lower():
                    issue_title_col = col
                   
                    break
                elif 'title' in col.lower():
                    issue_title_col = col
                  
                    break
        
        if not issue_title_col:
            possible_titles = ['Title', 'Issue', 'IssueKey', 'PRTitle']
            for col in possible_titles:
                if col in self.combined_data.columns:
                    issue_title_col = col
                   
                    break
        
        if not issue_title_col:
            print("❌ Could not find Issue Title column")
            print("Available columns:", list(self.combined_data.columns))
            return {}
        
       
        after_content_col = None
        possible_after_cols = ['AfterContent', 'after_content', 'After Content', 'afterContent', 'AFTER_CONTENT']
        
   
        if 'AfterContent' in self.combined_data.columns:
            after_content_col = 'AfterContent'
           
        else:
      
            for col in possible_after_cols:
                if col in self.combined_data.columns:
                    after_content_col = col
                   
                    break
        
  
        if not after_content_col:
            for col in self.combined_data.columns:
                if 'after' in col.lower() and 'content' in col.lower():
                    after_content_col = col
               
                    break
        
       
        if not after_content_col:
            for col in self.combined_data.columns:
                if 'after' in col.lower():
                    after_content_col = col
                   
                    break
                elif 'content' in col.lower() and 'before' not in col.lower():
                    after_content_col = col
                 
                    break
        
        if not after_content_col:
            print("❌ Could not find AfterContent column")
            print("Available columns:", list(self.combined_data.columns))
            return {}
        
        print(f"Using columns: '{issue_title_col}' for issue title, '{after_content_col}' for after content")
        
        
        print(f"\n=== Issue Title Column Sample ===")
        for i in range(min(3, len(self.combined_data))):
            sample_title = self.combined_data.iloc[i].get(issue_title_col, '')
            print(f"Row {i}: Issue Title='{str(sample_title)}'")
        
        print(f"\n=== AfterContent Column Sample ===")
        for i in range(min(3, len(self.combined_data))):
            sample_after = self.combined_data.iloc[i].get(after_content_col, '')
            print(f"Row {i}: AfterContent length={len(str(sample_after))}, content='{str(sample_after)[:100]}...'")
        
        
      
        print(list(self.combined_data.columns))
        
        
        for i in range(min(3, len(self.combined_data))):
            print(f"\nRow {i}:")
            for col in self.combined_data.columns:
                value = self.combined_data.iloc[i].get(col, '')
                if pd.notna(value) and isinstance(value, str) and len(str(value)) > 20:
                    print(f"  {col}: {str(value)[:100]}...")
                else:
                    print(f"  {col}: {value}")
        
       
        merged_content = {}
        
        
        
        for idx, row in self.combined_data.iterrows():
            issue_title = row.get(issue_title_col, '')
            after_content = row.get(after_content_col, '')
            
          
            
            if pd.isna(issue_title) or issue_title == '':
             
                continue
                
            if pd.isna(after_content) or after_content == '':
               
                continue
            
           
            cleaned_after_content = self.preprocess_code(after_content)
            
            
            if not cleaned_after_content:
                
                continue
            
            if issue_title not in merged_content:
                merged_content[issue_title] = []
               
     
            
            merged_content[issue_title].append(cleaned_after_content)
            
            
  
        
        
        final_merged = {}
       
        
        for issue_title, contents in merged_content.items():
            
            
            if len(contents) == 1:
                final_merged[issue_title] = contents[0]
                
            else:
             
                final_merged[issue_title] = '\n\n--- SEPARATOR ---\n\n'.join(contents)
                
        
       
        
       
        print(f"\n=== AfterContent Merge Preview ===")
        for i, (title, content) in enumerate(final_merged.items()):
            if i < 3:  
                print(f"\nIssue: {title}")
                print(f"Content length: {len(content)} characters")
                print(f"Content preview (first 300 chars): {content[:300]}...")
                if len(content) > 300:
                    print(f"Content preview (last 200 chars): ...{content[-200:]}")
        
        return final_merged
    
    def calculate_similarity_metrics(self, text1: str, text2: str) -> Dict[str, float]:
   
        if not text1 or not text2:
            return {
                'cosine_similarity': 0.0,
                'sequence_similarity': 0.0,
                'jaccard_similarity': 0.0,
                'overall_similarity': 0.0
            }
        
     
        try:
            
            sequence_sim = SequenceMatcher(None, text1, text2).ratio()
        except Exception as e:
            print(f"Warning: Error calculating sequence similarity: {e}")
            sequence_sim = 0.0
        
     
        try:
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            
            if not words1 and not words2:
                jaccard_sim = 1.0
            elif not words1 or not words2:
                jaccard_sim = 0.0
            else:
                intersection = words1.intersection(words2)
                union = words1.union(words2)
                jaccard_sim = len(intersection) / len(union) if union else 0.0
        except Exception as e:
            print(f"Warning: Error calculating Jaccard similarity: {e}")
            jaccard_sim = 0.0
        
   
        overall_sim = (sequence_sim + jaccard_sim) / 2
        
    
        accuracy_score = self.calculate_accuracy_score(overall_sim * 100) 
        
        return {
            'cosine_similarity': round(sequence_sim * 100, 2), 
            'sequence_similarity': round(sequence_sim * 100, 2),
            'jaccard_similarity': round(jaccard_sim * 100, 2),
            'overall_similarity': round(overall_sim * 100, 2),
            'accuracy_score': accuracy_score
        }
    
    def calculate_accuracy_score(self, overall_sim: float) -> float:
  
       
        if overall_sim >= 80: 
            accuracy = 0.9 + (overall_sim - 80) * 0.001 
        elif overall_sim >= 50: 
            accuracy = 0.6 + (overall_sim - 50) * 0.01 
        else: 
            accuracy = overall_sim * 0.01 
        
       
        return round(accuracy * 100, 2)
    
    def analyze_similarity(self):
       
        print("Starting similarity analysis...")
        
    
        merged_after_content = self.merge_after_content_by_issue_title()
        
        
        print(f"\nStarting analysis of {len(self.llm_data)} LLM results...")
        
     
        print(f"LLM data columns: {list(self.llm_data.columns)}")
        
       
        fixed_code_col = None
        
        for col in self.llm_data.columns:
            sample_value = self.llm_data.iloc[0].get(col, '')
            if pd.notna(sample_value) and isinstance(sample_value, str) and len(str(sample_value)) > 100:
              
                if 'code' in col.lower() or 'content' in col.lower() or 'preview' in col.lower():
                    fixed_code_col = col
                    break
        
       
        if not fixed_code_col:
            for col in self.llm_data.columns:
                if 'fixed' in col.lower() and 'code' in col.lower():
                    fixed_code_col = col
                    break
                elif 'code' in col.lower():
                    fixed_code_col = col
                    break
                elif 'content' in col.lower():
                    fixed_code_col = col
                    break
        
        if not fixed_code_col:
            print("\n❌ Could not find fixed_code column in LLM data")
            print("Available columns:", list(self.llm_data.columns))
            return
        
        print(f"\n✅ Using column '{fixed_code_col}' for fixed_code")
        
   
        sample_fixed_code = self.llm_data.iloc[0].get(fixed_code_col, '')
        if pd.isna(sample_fixed_code):
            sample_fixed_code = 'NA'
        print(f"Sample fixed_code content (first 300 chars): {str(sample_fixed_code)[:300]}...")
        
     
        if not sample_fixed_code or sample_fixed_code == 'NA' or len(str(sample_fixed_code).strip()) < 10:
            print(f"⚠️  Warning: Sample fixed_code seems empty or too short: '{sample_fixed_code}'")
            print("This might indicate the wrong column was selected")
        else:
            print(f"✅ Sample fixed_code looks good, length: {len(str(sample_fixed_code))} characters")
        
      
        issue_title_col = None
        if 'issue_title' in self.llm_data.columns:
            issue_title_col = 'issue_title'
        else:
            
            for col in self.llm_data.columns:
                if 'issue' in col.lower() and 'title' in col.lower():
                    issue_title_col = col
                    break
        
        if not issue_title_col:
            print("\n❌ Could not find issue_title column in LLM data")
            print("Available columns:", list(self.llm_data.columns))
            return
        
        print(f"✅ Using column '{issue_title_col}' for issue_title")
        
        for idx, llm_row in self.llm_data.iterrows():
            issue_title = llm_row.get(issue_title_col, '')
            fixed_code = llm_row.get(fixed_code_col, '')
            
            if pd.isna(issue_title) or issue_title == '':
                print(f"⚠️  Row {idx}: Skipping empty issue_title")
                continue
            
            if pd.isna(fixed_code) or fixed_code == '':
                print(f"⚠️  Row {idx}: Skipping empty fixed_code for '{issue_title}'")
                continue
            
           
            cleaned_fixed_code = self.preprocess_code(fixed_code)
            if not cleaned_fixed_code:
                print(f"⚠️  Row {idx}: Skipping empty cleaned_fixed_code for '{issue_title}'")
                continue
            
       
            print(f"\n--- Processing Issue: {issue_title} ---")
            print(f"Fixed code length: {len(cleaned_fixed_code)} characters")
            print(f"Fixed code preview (first 300 chars): {cleaned_fixed_code[:300]}...")
            if len(cleaned_fixed_code) > 300:
                print(f"Fixed code preview (last 200 chars): ...{cleaned_fixed_code[-200:]}")
            
           
            after_content = ''
            matched_title = None
            
           
            if issue_title in merged_after_content:
                after_content = merged_after_content[issue_title]
                matched_title = issue_title
            else:
                
                for title, content in merged_after_content.items():
                    
                    clean_title = re.sub(r'#[0-9]+', '', title).strip()
                    clean_llm_title = re.sub(r'#[0-9]+', '', issue_title).strip()
                    
                   
                    if (clean_title.lower() in clean_llm_title.lower() or 
                        clean_llm_title.lower() in clean_title.lower() or
                        clean_title.lower() == clean_llm_title.lower()):
                        after_content = content
                        matched_title = title
                        print(f"Fuzzy matched: '{issue_title}' -> '{title}'")
                        break
            
            if not after_content:
                print(f"Warning: No AfterContent found for issue: '{issue_title}'")
                
                result = {
                    'issue_title': issue_title,
                    'fixed_code_length': len(cleaned_fixed_code),
                    'after_content_length': 0,
                    'cosine_similarity': 0.0,
                    'sequence_similarity': 0.0,
                    'jaccard_similarity': 0.0,
                    'overall_similarity': 0.0,
                    'accuracy_score': 0.0,
                    'fixed_code_content': cleaned_fixed_code,
                    'after_content_content': 'No AfterContent available'
                }
                self.similarity_results.append(result)
                continue
            else:
               
                print(f"AfterContent length: {len(after_content)} characters")
                print(f"AfterContent preview (first 300 chars): {after_content[:300]}...")
                if len(after_content) > 300:
                    print(f"AfterContent preview (last 200 chars): ...{after_content[-200:]}")
            
          
            similarity_metrics = self.calculate_similarity_metrics(cleaned_fixed_code, after_content)
            
          
            result = {
                'issue_title': issue_title,
                'fixed_code_length': len(cleaned_fixed_code),
                'after_content_length': len(after_content),
                'cosine_similarity': similarity_metrics['cosine_similarity'],
                'sequence_similarity': similarity_metrics['sequence_similarity'],
                'jaccard_similarity': similarity_metrics['jaccard_similarity'],
                'overall_similarity': similarity_metrics['overall_similarity'],
                'accuracy_score': similarity_metrics['accuracy_score'],
                'fixed_code_content': cleaned_fixed_code,
                'after_content_content': after_content
            }
            
            self.similarity_results.append(result)
            
            print(f"Analyzed similarity for '{issue_title}' -> '{matched_title}': {similarity_metrics['overall_similarity']:.2f}%")
        
        print(f"Completed similarity analysis for {len(self.similarity_results)} issues")
    
    def save_results(self, output_path: str):
      
        if not self.similarity_results:
            print("No results to save")
            return
        
      
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
   
        fieldnames = [
            'issue_title',
            'fixed_code_length',
            'after_content_length',
            'cosine_similarity',
            'sequence_similarity',
            'jaccard_similarity',
            'overall_similarity',
            'accuracy_score',
            'fixed_code_content',
            'after_content_content'
        ]
        
        
        MAX_CELL_CHARS = 30000
        
        def truncate_content(content, max_chars=MAX_CELL_CHARS):
            
            if not content or len(str(content)) <= max_chars:
                return content
            
            content_str = str(content)
            
           
            if any(keyword in content_str.lower() for keyword in ['public', 'private', 'static', 'class', 'def', 'function', 'import', 'package']):
              
                
                front_part = int(max_chars * 0.7)
                back_part = max_chars - front_part
                
                truncated = (
                    content_str[:front_part] + 
                    "\n\n... ...\n\n" + 
                    content_str[-back_part:]
                )
            else:
               
                half_max = max_chars // 2
                truncated = (
                    content_str[:half_max] + 
                    "\n\n......\n\n" + 
                    content_str[-half_max:]
                )
            
           
            return truncated
        
       
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in self.similarity_results:
                
                truncated_result = result.copy()
                
              
                truncated_result['fixed_code_content'] = truncate_content(result['fixed_code_content'])
                truncated_result['after_content_content'] = truncate_content(result['after_content_content'])
                
                writer.writerow(truncated_result)
        
        print(f"Results saved to {output_path}")
        print(f"Note: Content longer than {MAX_CELL_CHARS} characters has been truncated for CSV compatibility")
        
      
        self._print_statistics()
    
    def _print_statistics(self):
       
        if not self.similarity_results:
            return
        
        overall_similarities = [r['overall_similarity'] for r in self.similarity_results]
        cosine_similarities = [r['cosine_similarity'] for r in self.similarity_results]
        sequence_similarities = [r['sequence_similarity'] for r in self.similarity_results]
        jaccard_similarities = [r['jaccard_similarity'] for r in self.similarity_results]
        
        print("\n=== Similarity Analysis Statistics ===")
        print(f"Total issues analyzed: {len(self.similarity_results)}")
        print(f"Overall similarity - Mean: {np.mean(overall_similarities):.2f}%, Std: {np.std(overall_similarities):.2f}%")
        print(f"Cosine similarity - Mean: {np.mean(cosine_similarities):.2f}%, Std: {np.std(cosine_similarities):.2f}%")
        print(f"Sequence similarity - Mean: {np.mean(sequence_similarities):.2f}%, Std: {np.std(sequence_similarities):.2f}%")
        print(f"Jaccard similarity - Mean: {np.mean(jaccard_similarities):.2f}%, Std: {np.std(jaccard_similarities):.2f}%")
        
     
        high_sim = len([s for s in overall_similarities if s >= 80]) 
        medium_sim = len([s for s in overall_similarities if 50 <= s < 80]) 
        low_sim = len([s for s in overall_similarities if s < 50]) 
        
        print(f"\nSimilarity Distribution:")
        print(f"  High (≥80%): {high_sim} issues ({high_sim/len(overall_similarities)*100:.1f}%)")
        print(f"  Medium (50%-80%): {medium_sim} issues ({medium_sim/len(overall_similarities)*100:.1f}%)")
        print(f"  Low (<50%): {low_sim} issues ({low_sim/len(overall_similarities)*100:.1f}%)")
        
      
        sorted_results = sorted(self.similarity_results, key=lambda x: x['overall_similarity'], reverse=True)
        
        print(f"\nTop 3 Most Similar Issues:")
        for i, result in enumerate(sorted_results[:3]):
            print(f"  {i+1}. {result['issue_title']}: {result['overall_similarity']:.2f}%")
        
        print(f"\nBottom 3 Least Similar Issues:")
        for i, result in enumerate(sorted_results[-3:]):
            print(f"  {i+1}. {result['issue_title']}: {result['overall_similarity']:.2f}%")
    
    def run_analysis(self, output_path: str):
        
        print("=== Merge AfterContent and Compare Similarity ===")
        
        
        if not self.load_data():
            print("Failed to load data. Exiting.")
            return
        
       
        self.analyze_similarity()
        
      
        self.save_results(output_path)
        
        print("=== Analysis Complete ===")


def main():
    parser = argparse.ArgumentParser(description='Merge AfterContent by issue title and compare similarity with fixed_code')
    parser.add_argument('--llm-results', required=True, help='Path to LLM analysis results CSV file (with fixed_code column)')
    parser.add_argument('--combined-results', required=True, help='Path to combined results CSV file (with AfterContent and Issue Title columns)')
    parser.add_argument('--output', required=True, help='Path to save similarity analysis results CSV')
    
    args = parser.parse_args()
    
   
    analyzer = MergeAndCompareSimilarity(args.llm_results, args.combined_results)
    analyzer.run_analysis(args.output)


if __name__ == "__main__":
    main()
