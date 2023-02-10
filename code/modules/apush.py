#!/usr/bin/env python
#-*- encoding: utf-8 -*-

import time, hashlib, uuid, traceback
import urllib
import urllib.parse
import urllib.request
import ssl

context = ssl._create_unverified_context()

ATXT_HOST = 'https://dom.aifetel.cc'
# ATXT_HOST = 'http://192.168.0.27:8087'
headers = {'user-agent': 'Mildred/3.3.3 (cc.aifetel.mildred; build:3.3.3; Linux) MildredServer/3.3.3', 'Accept-Encoding': 'gzip'}

def caclSignature(secretkey, timestamp, nonce):
    secretkey.extend([timestamp, nonce])
    secretkey.sort()
    return hashlib.sha1(''.join(secretkey).encode('utf8')).hexdigest()

def pushNotification(lid, sid, did, title, content, url):
    timestamp = str(time.time())
    nonce = hashlib.md5(uuid.uuid1().hex.encode('utf8')).hexdigest()
    signature = caclSignature([sid,did], timestamp, nonce)
    params = {"ts":timestamp, "nc":nonce, "sn":signature, "sync":'', "tl":title, "ct":content, "url":url}
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        f"{ATXT_HOST}/domapi/lic/{lid}/push", data=data, headers=headers
    )
    if ATXT_HOST.lower().startswith('https'):
        res = urllib.request.urlopen(req, context=context)
    else:
        res = urllib.request.urlopen(req)
    return res.read().decode("utf-8")
