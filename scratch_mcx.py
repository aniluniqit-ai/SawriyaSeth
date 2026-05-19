import json, urllib.parse, sys
from kotak_api import KotakNeoAPI

def check_mcx():
    with open('config/config.json') as f:
        cfg = json.load(f)
    api = KotakNeoAPI(cfg['kotak'])
    if not api.login():
        print("Login failed")
        return
        
    symbols = [
        "CRUDEOIL26MAYFUT",
        "CRUDEOIL26JUNFUT",
        "CRUDEOIL26MAY",
        "CRUDEOIL26MAY24",
        "CRUDEOIL-I",
        "CRUDEOILM26MAYFUT",
        "CRUDEOIL26MAYFUT.MCX",
        "CRUDEOIL"
    ]
    
    for sym in symbols:
        ltp = api.get_ltp(sym, "mcx_fo")
        print(f"mcx_fo|{sym} : LTP = {ltp}")

if __name__ == '__main__':
    check_mcx()
