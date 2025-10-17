#!/usr/bin/env python3
"""
Scan Notion database for pages with blank placeholder text.
"""
import sys
import ssl
import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.api_keys import get_notion_api_key
from src.utils.config import Config
from notion_client import Client

def main():
    # Initialize
    config = Config()
    notion_api_key = get_notion_api_key()
    database_id = '255a6c5dacd08083bc4fd57c6333b52b'

    # Disable SSL verification
    http_client = httpx.Client(verify=False)
    client = Client(auth=notion_api_key, client=http_client)

    print('🔍 Scanning Notion database for blank placeholder pages...\n')

    results = []
    has_more = True
    start_cursor = None
    page_count = 0

    while has_more:
        query_params = {'database_id': database_id, 'page_size': 100}
        if start_cursor:
            query_params['start_cursor'] = start_cursor

        response = client.databases.query(**query_params)

        for page in response['results']:
            page_count += 1
            page_id = page['id']

            # Get notebook name
            title_prop = page['properties'].get('Name', {})
            title_list = title_prop.get('title', [])
            notebook_name = title_list[0]['plain_text'] if title_list else 'Unknown'

            print(f'  Scanning {notebook_name}... ({page_count} notebooks)', end='\r')

            # Get all blocks
            try:
                blocks = client.blocks.children.list(block_id=page_id, page_size=100)

                # Check toggle blocks
                for block in blocks['results']:
                    if block['type'] == 'toggle':
                        toggle_content = block.get('toggle', {})
                        rich_text = toggle_content.get('rich_text', [])

                        if rich_text:
                            toggle_title = rich_text[0].get('text', {}).get('content', '')

                            if '📄 Page ' in toggle_title:
                                try:
                                    page_num = int(toggle_title.split('📄 Page ')[1].split(' ')[0].split('(')[0])
                                except:
                                    continue

                                # Check children
                                children = toggle_content.get('children', [])
                                for child in children:
                                    if child['type'] == 'paragraph':
                                        para_text = child.get('paragraph', {}).get('rich_text', [])
                                        if para_text:
                                            text_content = para_text[0].get('text', {}).get('content', '')

                                            if 'This appears to be a blank' in text_content or 'completely empty page' in text_content:
                                                results.append({
                                                    'notebook': notebook_name,
                                                    'page': page_num,
                                                    'preview': text_content[:80]
                                                })
                                                print(f'  ⚠️  Found: {notebook_name} page {page_num}' + ' ' * 30)
                                                break
            except Exception as e:
                print(f'\n  Error scanning {notebook_name}: {e}')
                continue

        has_more = response['has_more']
        start_cursor = response.get('next_cursor')

    print(f'\n\nScanned {page_count} notebooks\n')

    # Print results
    if results:
        print(f'Found {len(results)} pages with blank placeholders:\n')
        print(f'{"Notebook":<25} {"Page":<10} {"Preview":<60}')
        print('-' * 95)
        for r in results:
            print(f'{r["notebook"]:<25} {str(r["page"]):<10} {r["preview"]:<60}')

        # Save to file
        output_file = Path(__file__).parent.parent / 'blank_pages_report.txt'
        with open(output_file, 'w') as f:
            f.write(f'Blank Placeholder Pages Report\n')
            f.write(f'Generated: {page_count} notebooks scanned\n\n')
            f.write(f'{"Notebook":<25} {"Page":<10}\n')
            f.write('-' * 35 + '\n')
            for r in results:
                f.write(f'{r["notebook"]:<25} {r["page"]}\n')
        print(f'\n📄 Report saved to: {output_file}')
    else:
        print('✅ No blank placeholder pages found!')

if __name__ == '__main__':
    main()
