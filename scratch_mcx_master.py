import json, urllib.request, requests
from kotak_api import KotakNeoAPI
import csv, io

def find_mcx_symbols():
    with open('config/config.json', encoding='utf-8') as f:
        cfg = json.load(f)
    api = KotakNeoAPI(cfg['kotak'])
    if not api.login():
        print("Login failed")
        return
        
    try:
        url = f"{api.base_url}/script-details/1.0/masterscrip/file-paths"
        r = api._session.get(url, headers={"Authorization": api.access_token}, timeout=10)
        data = r.json()
        
        # Look for MCX file
        mcx_url = None
        for path in data.get('data', {}).get('filesPaths', []):
            if 'mcx_fo' in path.lower():
                mcx_url = path
                break
                
        if not mcx_url:
            print("Could not find mcx_fo URL")
            return
            
        print("Downloading MCX master file...", mcx_url)
        resp = requests.get(mcx_url)
        content = resp.text
        
        reader = csv.DictReader(io.StringIO(content))
        first_row = next(reader)
        print("CSV Headers:", list(first_row.keys()))
        print("First row data:", first_row)
                
        for sym in crude_futs[:3]:
            print(f"{sym}:", api.get_ltp(sym, 'mcx_fo'))
        for sym in ng_futs[:3]:
            print(f"{sym}:", api.get_ltp(sym, 'mcx_fo'))
        for sym in gold_futs[:3]:
            print(f"{sym}:", api.get_ltp(sym, 'mcx_fo'))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    find_mcx_symbols()
