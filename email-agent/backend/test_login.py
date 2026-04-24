import urllib.request
import json

try:
    req = urllib.request.Request('http://localhost:8000/auth/login')
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except Exception as e:
    print('Failed:', e)
