import requests
import re
from bs4 import BeautifulSoup
import urllib3
import urllib.parse
urllib3.disable_warnings()

url = f"https://vbpl.vn/pages/searchvbpq.aspx?Keyword={urllib.parse.quote('01/2021/TT-BKHĐT')}"
print(f"Searching: {url}")
res = requests.get(url, verify=False)
soup = BeautifulSoup(res.text, 'html.parser')

for a in soup.find_all('a', href=True):
    href = a['href']
    if 'ItemID=' in href and '01/2021/TT-BKHĐT' in a.text:
        print(f"FOUND: {href}")
        
    elif 'ItemID=' in href:
        print(f"Other link: {href} ({a.text.strip()})")

