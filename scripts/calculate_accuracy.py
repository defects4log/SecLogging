

import argparse
import pandas as pd
import os
import csv
from urllib.parse import urlparse


def normalize_url(url):
    
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


def load_llm_results(llm_results_path):
    
    print(f"Loading LLM analysis results from {llm_results_path}")
    
    try:
        
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']
        
        for encoding in encodings:
            try:
                llm_df = pd.read_csv(llm_results_path, encoding=encoding)
                print(f"Successfully loaded with encoding: {encoding}")
                print(f"Loaded {len(llm_df)} entries from LLM analysis results")
                print(f"LLM results columns: {llm_df.columns.tolist()}")
                return llm_df
            except UnicodeDecodeError:
                print(f"Failed to load with encoding {encoding}, trying next...")
            except Exception as e:
                print(f"Error loading with encoding {encoding}: {e}")
        
        print("Failed to load with any encoding")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error loading LLM analysis results: {e}")
        return pd.DataFrame()


def load_ground_truth(ground_truth_path):
    
    print(f"Loading ground truth data from {ground_truth_path}")
    
    try:
    
        encodings = ['utf-8-sig', 'utf-8', 'gbk', 'latin-1']
        
        for encoding in encodings:
            try:
                ground_truth_df = pd.read_csv(ground_truth_path, encoding=encoding)
                print(f"Successfully loaded with encoding: {encoding}")
                print(f"Loaded {len(ground_truth_df)} entries from ground truth data")
                print(f"Ground truth columns: {ground_truth_df.columns.tolist()}")
                return ground_truth_df
            except UnicodeDecodeError:
                print(f"Failed to load with encoding {encoding}, trying next...")
            except Exception as e:
                print(f"Error loading with encoding {encoding}: {e}")
        
        print("Failed to load with any encoding")
        return pd.DataFrame()
    except Exception as e:
        print(f"Error loading ground truth data: {e}")
        return pd.DataFrame()


def match_results(llm_df, ground_truth_df):
    
    print("Matching LLM results with ground truth data based on issue title...")
    
    matched_data = []
    
  
    title_to_ground_truth = {}
    
   
    for _, row in ground_truth_df.iterrows():
        issue_title = row.get('Issue Title', '')
        category = row.get('Category', '') 
        pattern = row.get('Pattern', '')   
        pr_url = row.get('PR URL', '')
        issue_url = row.get('Issue URL', '')
        
        if not issue_title:
            continue
            
        print(f"Found ground truth: '{issue_title}' with category '{category}' and pattern '{pattern}'")
            
        
        normalized_title = issue_title.lower().strip()
        
        title_to_ground_truth[normalized_title] = {
            'issue_title': issue_title,
            'category': category,
            'pattern': pattern,
            'pr_url': pr_url,
            'issue_url': issue_url
        }
    
 
    for _, row in llm_df.iterrows():
       
        llm_issue_title = None
        for column in ['issue_title', 'IssueTitle']:
            if column in row and pd.notna(row[column]) and row[column]:
                llm_issue_title = row[column]
                break
        
        if not llm_issue_title:
            print(f"Skipping LLM result without issue title: {row.to_dict()}")
            continue
            
        
        normalized_llm_title = llm_issue_title.lower().strip()
        
   
        if normalized_llm_title in title_to_ground_truth:
            ground_truth = title_to_ground_truth[normalized_llm_title]
            matched_data.append({
                'issue_title': llm_issue_title,
                'url': row.get('url', ''),
                'llm_category': row.get('category', ''),
                'llm_pattern': row.get('pattern', ''),
                'ground_truth_category': ground_truth['category'],
                'ground_truth_pattern': ground_truth['pattern'],
                'category_correct': row.get('category', '') == ground_truth['category'],
                'pattern_correct': row.get('pattern', '') == ground_truth['pattern']
            })
            continue
            
     
        matched = False
        for gt_title, ground_truth in title_to_ground_truth.items():
           
            if normalized_llm_title in gt_title or gt_title in normalized_llm_title:
                matched_data.append({
                    'issue_title': llm_issue_title,
                    'ground_truth_title': ground_truth['issue_title'],
                    'url': row.get('url', ''),
                    'llm_category': row.get('category', ''),
                    'llm_pattern': row.get('pattern', ''),
                    'ground_truth_category': ground_truth['category'],
                    'ground_truth_pattern': ground_truth['pattern'],
                    'category_correct': row.get('category', '') == ground_truth['category'],
                    'pattern_correct': row.get('pattern', '') == ground_truth['pattern']
                })
                matched = True
                break
        
        if not matched:
            print(f"No match found for issue title: {llm_issue_title}")
    
    print(f"Matched {len(matched_data)} entries")
    return matched_data


def calculate_accuracy(matched_data):
    
    print("Calculating accuracy...")
    
    if not matched_data:
        print("No matched data to calculate accuracy")
        return 0.0, 0.0, {}, {}
    
    
    issue_groups = {}
    for item in matched_data:
        issue_title = item.get('issue_title', 'Unknown Issue')
        if issue_title not in issue_groups:
            issue_groups[issue_title] = []
        issue_groups[issue_title].append(item)
    
 
    issue_category_correct = 0
    issue_pattern_correct = 0
    
    for issue_title, items in issue_groups.items():
        if any(item['category_correct'] for item in items):
            issue_category_correct += 1
        if any(item['pattern_correct'] for item in items):
            issue_pattern_correct += 1
    
 
    total_issues = len(issue_groups)
   
    overall_category_accuracy = issue_category_correct / total_issues if total_issues > 0 else 0.0
    overall_pattern_accuracy = issue_pattern_correct / total_issues if total_issues > 0 else 0.0
    

    match_category_correct = sum(1 for item in matched_data if item['category_correct'])
    match_pattern_correct = sum(1 for item in matched_data if item['pattern_correct'])
    
    print(f"Per-match Category Accuracy: {match_category_correct/len(matched_data):.2%} ({match_category_correct}/{len(matched_data)})")
    print(f"Per-match Pattern Accuracy: {match_pattern_correct/len(matched_data):.2%} ({match_pattern_correct}/{len(matched_data)})")
    
    print(f"Overall Category Accuracy: {overall_category_accuracy:.2%} ({issue_category_correct}/{total_issues})")
    print(f"Overall Pattern Accuracy: {overall_pattern_accuracy:.2%} ({issue_pattern_correct}/{total_issues})")
    
   
    results_by_category = {}
    
    
    category_groups = {}
    for item in matched_data:
        category = item['ground_truth_category']
        if category not in category_groups:
            category_groups[category] = []
        category_groups[category].append(item)
    
   
    for category, items in category_groups.items():
        category_correct = sum(1 for item in items if item['category_correct'])
        pattern_correct = sum(1 for item in items if item['pattern_correct'])
        
        category_accuracy = category_correct / len(items) if items else 0.0
        pattern_accuracy = pattern_correct / len(items) if items else 0.0
        
        results_by_category[category] = {
            'count': len(items),
            'category_accuracy': category_accuracy,
            'pattern_accuracy': pattern_accuracy
        }
        
        print(f"Category {category}: {len(items)} items")
        print(f"  - Category Accuracy: {category_accuracy:.2%} ({category_correct}/{len(items)})")
        print(f"  - Pattern Accuracy: {pattern_accuracy:.2%} ({pattern_correct}/{len(items)})")
    
   
    results_by_issue = {}

    issue_groups = {}
    for item in matched_data:
        issue_title = item.get('issue_title', 'Unknown Issue')
        if issue_title not in issue_groups:
            issue_groups[issue_title] = []
        issue_groups[issue_title].append(item)
    
   
    for issue_title, items in issue_groups.items():
        category_correct = sum(1 for item in items if item['category_correct'])
        pattern_correct = sum(1 for item in items if item['pattern_correct'])
        
        category_accuracy = category_correct / len(items) if items else 0.0
        pattern_accuracy = pattern_correct / len(items) if items else 0.0
        
       
        ground_truth_category = items[0]['ground_truth_category'] if items else ''
        ground_truth_pattern = items[0]['ground_truth_pattern'] if items else ''
        
     
        llm_category = items[0]['llm_category'] if items else ''
        llm_pattern = items[0]['llm_pattern'] if items else ''
        
        results_by_issue[issue_title] = {
            'count': len(items),
            'category_accuracy': category_accuracy,
            'pattern_accuracy': pattern_accuracy,
            'ground_truth_category': ground_truth_category,
            'ground_truth_pattern': ground_truth_pattern,
            'llm_category': llm_category,
            'llm_pattern': llm_pattern
        }
        
        print(f"Issue: {issue_title}")
        print(f"  - Category Accuracy: {category_accuracy:.2%} ({category_correct}/{len(items)})")
        print(f"  - Pattern Accuracy: {pattern_accuracy:.2%} ({pattern_correct}/{len(items)})")
        print(f"  - Ground Truth: {ground_truth_category}/{ground_truth_pattern}")
        print(f"  - LLM Result: {llm_category}/{llm_pattern}")
    
    return overall_category_accuracy, overall_pattern_accuracy, results_by_category, results_by_issue


def save_results(matched_data, category_accuracy, pattern_accuracy, results_by_category, results_by_issue, output_path):
    

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
 
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
       
        total_issues = len(results_by_issue)
       
        category_yes_count = sum(1 for _, results in results_by_issue.items() if results['category_accuracy'] == 1.0)
        pattern_yes_count = sum(1 for _, results in results_by_issue.items() if results['pattern_accuracy'] == 1.0)
        
     
        category_accuracy = category_yes_count / total_issues if total_issues > 0 else 0.0
        pattern_accuracy = pattern_yes_count / total_issues if total_issues > 0 else 0.0
        
        writer.writerow(['Total Issues', total_issues])
        writer.writerow(['Category Accuracy', f"{category_accuracy:.2%} ({category_yes_count}/{total_issues})"])
        writer.writerow(['Pattern Accuracy', f"{pattern_accuracy:.2%} ({pattern_yes_count}/{total_issues})"])
        writer.writerow([])
        

        writer.writerow(['Accuracy by Category'])
        writer.writerow(['Category', 'Total Count', 'Category Accuracy', 'Pattern Accuracy'])
        
   
        category_stats = {}
        pattern_stats = {}
        
        
        for item in matched_data:
            gt_category = item['ground_truth_category']
            gt_pattern = item['ground_truth_pattern']
            
            if gt_category not in category_stats:
                category_stats[gt_category] = {'total': 0, 'correct': 0}
            
            if gt_pattern not in pattern_stats:
                pattern_stats[gt_pattern] = {'total': 0, 'correct': 0}
            
         
            issue_title = item.get('issue_title', 'Unknown Issue')
            if issue_title not in category_stats[gt_category].get('issues', set()):
                category_stats[gt_category]['total'] += 1
                category_stats[gt_category].setdefault('issues', set()).add(issue_title)
                
                if item['category_correct']:
                    category_stats[gt_category]['correct'] += 1
            
            if issue_title not in pattern_stats[gt_pattern].get('issues', set()):
                pattern_stats[gt_pattern]['total'] += 1
                pattern_stats[gt_pattern].setdefault('issues', set()).add(issue_title)
                
                if item['pattern_correct']:
                    pattern_stats[gt_pattern]['correct'] += 1
        
     
        for category, stats in sorted(category_stats.items(), key=lambda x: str(x[0])):
            if stats['total'] > 0:
                accuracy = stats['correct'] / stats['total']
                
                pattern_accuracy = results_by_category.get(category, {}).get('pattern_accuracy', 0.0)
                writer.writerow([
                    category,
                    stats['total'],
                    f"{accuracy:.2%} ({stats['correct']}/{stats['total']})",
                    f"{pattern_accuracy:.2%}"
                ])
        
        writer.writerow([])
        
      
        writer.writerow(['Accuracy by Pattern'])
        writer.writerow(['Pattern', 'Total Count', 'Pattern Accuracy'])
        
        for pattern, stats in sorted(pattern_stats.items(), key=lambda x: str(x[0])):
            if stats['total'] > 0:
                accuracy = stats['correct'] / stats['total']
                writer.writerow([
                    pattern,
                    stats['total'],
                    f"{accuracy:.2%} ({stats['correct']}/{stats['total']})"
                ])
        
        writer.writerow([])
        
   
        writer.writerow(['Detailed Issue Information'])
        writer.writerow([
            'Issue Title', 
            'Ground Truth Category', 
            'Ground Truth Pattern', 
            'LLM Category', 
            'LLM Pattern', 
            'Category Correct', 
            'Pattern Correct'
        ])
        
        for issue_title, results in results_by_issue.items():
            writer.writerow([
                issue_title,
                results['ground_truth_category'],
                results['ground_truth_pattern'],
                results['llm_category'],
                results['llm_pattern'],
                'Yes' if results['category_accuracy'] == 1.0 else 'No',
                'Yes' if results['pattern_accuracy'] == 1.0 else 'No'
            ])
    
    print(f"Results saved to {output_path}")
    print(f"Total issues: {total_issues}")
    print(f"Category accuracy: {category_accuracy:.2%} ({category_yes_count}/{total_issues})")
    print(f"Pattern accuracy: {pattern_accuracy:.2%} ({pattern_yes_count}/{total_issues})")
    

    print("\nAccuracy by Category:")
    for category, stats in sorted(category_stats.items(), key=lambda x: str(x[0])):
        if stats['total'] > 0:
            accuracy = stats['correct'] / stats['total']
            print(f"  {category}: {accuracy:.2%} ({stats['correct']}/{stats['total']})")
    
    print("\nAccuracy by Pattern:")
    for pattern, stats in sorted(pattern_stats.items(), key=lambda x: str(x[0])):
        if stats['total'] > 0:
            accuracy = stats['correct'] / stats['total']
            print(f"  {pattern}: {accuracy:.2%} ({stats['correct']}/{stats['total']})")
    
   
    print("\nDetailed matched data:")
    for item in matched_data:
        print(f"Issue: {item.get('issue_title', 'Unknown')}")
        print(f"  Ground Truth: {item.get('ground_truth_category', 'Unknown')}/{item.get('ground_truth_pattern', 'Unknown')}")
        print(f"  LLM Result: {item.get('llm_category', 'Unknown')}/{item.get('llm_pattern', 'Unknown')}")


def evaluate(llm_results_path, ground_truth_path):

    llm_df = load_llm_results(llm_results_path)
    ground_truth_df = load_ground_truth(ground_truth_path)
    
    if llm_df.empty or ground_truth_df.empty:
        print("Error: Failed to load data")
        return
    

    matched_data = match_results(llm_df, ground_truth_df)
    
    if not matched_data:
        print("Error: No matched data")
        return
    

    category_accuracy, pattern_accuracy, results_by_category, results_by_issue = calculate_accuracy(matched_data)
    
    return category_accuracy, pattern_accuracy, results_by_category, results_by_issue

def main():
    parser = argparse.ArgumentParser(description='Calculate accuracy of LLM analysis results')
    parser.add_argument('--llm-results', required=True, help='Path to the LLM analysis results CSV file')
    parser.add_argument('--ground-truth', required=True, help='Path to the ground truth CSV file')
    parser.add_argument('--output', required=True, help='Path to save the output CSV file')
    
    args = parser.parse_args()
    

    llm_df = load_llm_results(args.llm_results)
    ground_truth_df = load_ground_truth(args.ground_truth)
    
    if llm_df.empty or ground_truth_df.empty:
        print("Error: Failed to load data")
        return
    

    matched_data = match_results(llm_df, ground_truth_df)
    
    if not matched_data:
        print("Error: No matched data")
        return
    

    category_accuracy, pattern_accuracy, results_by_category, results_by_issue = calculate_accuracy(matched_data)
    
  
    save_results(matched_data, category_accuracy, pattern_accuracy, results_by_category, results_by_issue, args.output)


if __name__ == "__main__":
    main()

