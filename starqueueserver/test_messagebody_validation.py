import requests
import sys

# this tests the MessageBody validation
# it sends every unicode character to the back end


data = {
    "Action": "MessageSend",
    "MessageBody": "",
    "MessageRetentionPeriod": "2020-10-15T12:00:00Z",
    "Version": "2012-11-05",
}
SERVERADDRESS = '127.0.0.1'
url = f'http://{SERVERADDRESS}:8000/111111111111/12312?param1=foo'

successes = 0
errors = 0
rowpos = 0
for i in range(sys.maxunicode):
    data["MessageBody"] = chr(i)
    try:
        r = requests.post(url, data=data)
    except Exception as e:
        errors += 1
        print(repr(e), traceback.format_exc())
        continue
    #print(r.text)
    #print(r.status_code)
    print('.', end="", flush=True)
    if r.status_code == 200:
        successes += 1
        continue
    if r.status_code == 400:
        errors += 1
        continue
    sys.exit()
    print(r.raw)
    if i > 1:
        sys.exit()
    if rowpos < 80:
        # print(chr(i).encode('raw_unicode_escape'), end="")
        try:
            print(chr(i), end="")
        except Exception as e:
            if type(e).__name__ not in exceptions:
                exceptions[type(e).__name__] = 1
            else:
                exceptions[type(e).__name__] += 1
        rowpos += 1
    else:
        try:
            print(chr(i), end="")
        except Exception as e:
            if type(e).__name__ not in exceptions:
                exceptions[type(e).__name__] = 1
            else:
                exceptions[type(e).__name__] += 1
        # print(chr(i).encode('raw_unicode_escape'))
        rowpos = 0
    continue

    # "Content-Type: application/x-www-form-urlencoded"
    r = requests.post(url, data=data)
    print(r.text)
    print(r.status_code)
    print(r.raw)
    print(r.json)
print('successes', successes)
print('errors', errors)

