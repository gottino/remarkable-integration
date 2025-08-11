import os
import json
import re
import pandas as pd

def extract_ascii_text(binary_data, min_length=10):
    """Extract sequences of ASCII characters that are at least `min_length` long."""
    ascii_text = re.findall(b'[ -~]{%d,}' % min_length, binary_data)
    return [text.decode('utf-8') for text in ascii_text]

def clean_extracted_text(text_list):
    """Clean and filter extracted text, excluding specific unwanted content."""
    unwanted_text = {
        "reMarkable .lines file, version=6",
        "reMarkable .lines file, version=3"
    }
    cleaned_sentences = []
    
    for text in text_list:
        cleaned_text = text.replace("l!", "").strip()  # Remove "l!" sequences
        
        if not cleaned_text or cleaned_text in unwanted_text:
            continue
        
        # Apply heuristics
        if not is_mostly_text(cleaned_text):
            continue
        if not has_enough_words(cleaned_text):
            continue
        if not has_low_symbol_ratio(cleaned_text):
            continue

        cleaned_sentences.append(cleaned_text)
    
    return cleaned_sentences

def is_mostly_text(text, threshold=0.6):
    letters = sum(c.isalpha() for c in text)
    return letters / max(len(text), 1) > threshold

def has_enough_words(text, min_words=3):
    return len(text.split()) >= min_words

def has_low_symbol_ratio(text, threshold=0.2):
    symbols = sum(not c.isalnum() and not c.isspace() for c in text)
    return symbols / max(len(text), 1) < threshold


def find_content_and_rm_files(directory):
    """
    Identify all .content files with valid file types (e.g., epub, pdf)
    and their associated .rm files in subdirectories.
    Args:
        directory (str): The root directory to search for .content files and corresponding .rm files.
    Returns:
        dict: A mapping of each valid .content file to its associated .rm file paths.
    """
    content_to_rm_files = {}

    # Find all .content files
    for root, _, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(".content"):
                content_file_path = os.path.join(root, file_name)
                
                # Read the .content file to check its fileType
                with open(content_file_path, 'r') as f:
                    content_data = json.load(f)
                
                # Only process files with fileType "epub" or "pdf"
                if content_data.get("fileType") not in ["epub", "pdf"]:
                    print(f"Skipping {content_file_path}: Invalid fileType '{content_data.get('fileType')}'.")
                    continue
                
                # Derive the subdirectory name from the .content file name
                content_file_id = os.path.splitext(os.path.basename(content_file_path))[0]
                subdirectory = os.path.join(directory, content_file_id)
                
                # Collect .rm files in the corresponding subdirectory
                rm_files = []
                if os.path.exists(subdirectory) and os.path.isdir(subdirectory):
                    for rm_file in os.listdir(subdirectory):
                        if not rm_file.endswith(".rm"):
                            continue

                        rm_base = os.path.splitext(rm_file)[0]
                        json_path = os.path.join(subdirectory, f"{rm_base}-metadata.json")

                        if os.path.exists(json_path):
                            print(f"Skipping {rm_file}: matching .json file exists.")
                            continue

                        rm_files.append(os.path.join(subdirectory, rm_file))
                
                # Map the valid .content file to its associated .rm files
                if rm_files:
                    content_to_rm_files[content_file_path] = rm_files

    return content_to_rm_files



def process_rm_files(rm_file_paths, content_file_path):
    # --- Step 1: Load the .content file ---
    with open(content_file_path, 'r') as f:
        content_data = json.load(f)

    # --- Step 2: Load the .metadata file ---
    content_file_id = os.path.splitext(os.path.basename(content_file_path))[0]
    metadata_file_path = os.path.join(os.path.dirname(content_file_path), content_file_id + ".metadata")
    
    visible_name = "Unknown Title"
    if os.path.exists(metadata_file_path):
        with open(metadata_file_path, 'r') as f:
            metadata = json.load(f)
            visible_name = metadata.get("visibleName", visible_name)

    # --- Step 3: Extract page mappings ---
    pages_data = content_data.get("cPages", {}).get("pages", [])
    id_to_page_mapping = {
        page["id"]: page["redir"]["value"]
        for page in pages_data
        if "id" in page and "redir" in page and "value" in page["redir"]
    }

    # --- Step 4: Extract and clean text from .rm files ---
    results = []
    for file_path in rm_file_paths:
        file_id = os.path.splitext(os.path.basename(file_path))[0]
        with open(file_path, 'rb') as f:
            binary_content = f.read()

        # Extract and clean text
        extracted_text = extract_ascii_text(binary_content)
        cleaned_text = clean_extracted_text(extracted_text)

        # Skip files with no valid highlights
        if not cleaned_text:
            print(f"Skipping {file_path}: No valid highlights found.")
            continue

        # Get the associated page number
        page_number = id_to_page_mapping.get(file_id, "Unknown")

        # Store results
        for sentence in cleaned_text:
            results.append({
                "Title": visible_name,
                "File Name": os.path.basename(file_path),
                "Extracted Sentence": sentence,
                "Page Number": page_number
            })

    # --- Step 5: Create and return DataFrame ---
    df_results = pd.DataFrame(results)
    return df_results


# Example usage:
if __name__ == "__main__":
    # Define the root directory containing the .content files and subdirectories
    directory = "/Users/gabriele/Documents/Development/rmsync/extract_test2"
    
    # Get .content files and their associated .rm files
    content_to_rm_files = find_content_and_rm_files(directory)
    
    if not content_to_rm_files:
        print("No .content files with corresponding .rm files found!")
    else:
        for content_file, rm_files in content_to_rm_files.items():
            print(f"Processing .content file: {content_file}")
            print(f"Found {len(rm_files)} .rm files in subdirectory.")
            
            # Process the .rm files for this .content file
            result_df = process_rm_files(rm_files, content_file)
            
            if not result_df.empty:
                # Save the results for this .content file
                content_file_id = os.path.splitext(os.path.basename(content_file))[0]
                output_csv = os.path.join(directory, f"{content_file_id}_extracted_text_with_pages.csv")
                result_df.to_csv(output_csv, index=False)
                print(f"Results saved to: {output_csv}")
            else:
                print(f"No highlights extracted from {content_file}. No file created.")