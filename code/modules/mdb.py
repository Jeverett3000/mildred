#!/usr/bin/env python
#-*- encoding: utf-8 -*-


import os, base64, time, traceback, json, random, hashlib
from datetime import datetime, date, timedelta
import yaml, web, rsa

from helper import utils, formator
from . import mdocker

dbsl = web.config.vars.get('dbsql', None)

def initDBConnection():
    global dbsl
    if 'dbsql' not in web.config.vars:
        dbfile = utils.prefixStorageDir('domdb.db')
        web.config.vars.dbsql = web.database(dbn='sqlite', db=dbfile)
        needInit = not os.path.isfile(dbfile)
        dbsl = web.config.vars.dbsql
        try:
            web.config.vars.dbsql.query("select sqlite_version() version")
            if needInit: initSchema()
            upgradeSchema()
            load_pubkeys()
            load_alerts()
            web.config.vars['enable_stat'] = get_syskey('ENABLE_STAT', '0')
        except Exception as e:
            traceback.print_exc()
            return False
    return True

SQL_SCHEMA_CREATE = [
'''CREATE TABLE IF NOT EXISTS DM_CONFIG (
    CKEY        VARCHAR(60) NOT NULL PRIMARY KEY,
    CVAL        VARCHAR(60)
);''',
'''INSERT INTO DM_CONFIG(CKEY, CVAL) VALUES('VERSION', '1')''',
'''INSERT INTO DM_CONFIG(CKEY, CVAL) VALUES('ENABLE_BIND', '1')''',
'''INSERT INTO DM_CONFIG(CKEY, CVAL) VALUES('ENABLE_STAT', '1')''',
'''CREATE TABLE IF NOT EXISTS DM_CLIENTS (
    LICENSEID   VARCHAR(60)   NOT NULL PRIMARY KEY ,
    SERVERID    VARCHAR(60)   NOT NULL ,
    SERVERNAME  VARCHAR(60)   NOT NULL ,
    SERVERURL   VARCHAR(90)   NOT NULL ,
    PUBKEY      VARCHAR(4096) NOT NULL ,
    DEVICEID    VARCHAR(60) ,
    DEVICENAME  VARCHAR(90) ,
    ISPRIMARY   INTEGER,
    OSNAME      VARCHAR(90),
    push_expire DATETIME,
    code_server VARCHAR(200)
);''',
'''CREATE TABLE IF NOT EXISTS DM_STATS (
    STID        INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    CNAME       VARCHAR(60) NOT NULL ,
    DATASTAMP   DATETIME NOT NULL ,
    ST01        DECIMAL(6,4) ,
    ST02        INTEGER ,
    ST03        DECIMAL(6,4) ,
    ST04        INTEGER ,
    ST05        INTEGER ,
    ST06        INTEGER ,
    ST07        INTEGER ,
    ST08        INTEGER ,
    ST09        INTEGER ,
    ST10        INTEGER ,
    ST11        INTEGER
);''',
'''CREATE INDEX IF NOT EXISTS IDX_ST1 ON DM_STATS(CNAME, DATASTAMP);''',
'''CREATE TABLE IF NOT EXISTS DM_ALERTS (
    ALID        INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    LICENSEID   VARCHAR(60) NOT NULL ,
    CNAME       VARCHAR(60) NOT NULL ,
    ALTYPE      INTEGER ,
    ALSTR       VARCHAR(200) ,
    ALVAL       INTEGER ,
    ALENABLED   SMALLINT ,
    ALPUSH      SMALLINT ,
    ALLEVEL     SMALLINT
);''',
'''CREATE INDEX IF NOT EXISTS IDX_ALT1 ON DM_ALERTS(CNAME);''',
'''CREATE TABLE IF NOT EXISTS DM_MESSAGE (
    MSGID       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    ALID        INTEGER NOT NULL  ,
    MSGSTAMP    DATETIME ,
    ISREAD      SMALLINT ,
    ISPUSHED    SMALLINT ,
    MSGKEYWORD  VARCHAR(200) ,
    MSGBODY     VARCHAR(800)
);''',
'''CREATE INDEX IF NOT EXISTS IDX_MSG1 ON DM_MESSAGE(ISREAD);''',
'''CREATE TABLE IF NOT EXISTS DM_COMPOSE (
    CMPSID      INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    ALIAS       VARCHAR(60),
    FILEPATH    VARCHAR(200) NOT NULL,
    FOLDER      VARCHAR(200)
);''',
]

SQL_SCHEMA_UPDATE = {
    '2': [''],
    '3': ['ALTER TABLE DM_MESSAGE ADD COLUMN MSGURL VARCHAR(500)',
          'ALTER TABLE DM_CLIENTS ADD COLUMN EXNOTIISON INTEGER',
          'ALTER TABLE DM_CLIENTS ADD COLUMN EXNOTIPASS VARCHAR(60)',
         ],
}

def initSchema():
    if not dbsl: return
    for sql in SQL_SCHEMA_CREATE:
        m = dbsl.query(sql)

def upgradeSchema():
    if not dbsl: return
    cver = get_syskey('VERSION', '1')
    for nver, sqls in SQL_SCHEMA_UPDATE.items():
        if nver > cver:
            for sql in sqls:
                m = dbsl.query(sql)
            set_syskey('VERSION', nver)

def get_syskey(key, defval=None):
    if not dbsl: return
    m = web.listget(dbsl.select("DM_CONFIG", vars=locals(), where="CKEY=$key").list(), 0, None)
    return m.CVAL if m else defval

def set_syskey(key, val):
    if not dbsl: return
    if web.listget(dbsl.select("DM_CONFIG", vars=locals(), where="CKEY=$key").list(), 0, None):
        dbsl.update("DM_CONFIG", vars=locals(), where="CKEY=$key", CVAL=val)
    else:
        dbsl.insert("DM_CONFIG", CKEY=key, CVAL=val)


def load_pubkeys():
    if not dbsl: return
    web.config.vars.pubkeys = dict([(x.LICENSEID, x) for x in dbsl.select("DM_CLIENTS").list()])

def gen_rsakey():
    import rsa
    (pubkey, prikey) = rsa.newkeys(1024)
    return pubkey.save_pkcs1().decode(), prikey.save_pkcs1().decode()

def check_signature(lid, ts, nonce, sig):
    if not dbsl: return {'errmsg': 'No database'}
    if not lid: return {'errmsg': 'Invalid request'}
    if not sig: return {'errmsg': 'Invalid signature'}
    if not ts: return {'errmsg': 'Invalid request'}
    pempub = web.config.vars.pubkeys.get(lid,{}).get('PUBKEY','')
    if not pempub:
        load_pubkeys()
        pempub = web.config.vars.pubkeys.get(lid,{}).get('PUBKEY','')
    if not pempub: return {'errmsg': 'No such client'}
    sig = utils.base64urlToBase64(sig)
    vdata = [lid, ts, nonce]
    vdata.sort()
    try:
        if time.time()-int(ts.split('.')[0])>15:
            return {'errmsg': 'Invalid signature'}
        pubkey = rsa.PublicKey.load_pkcs1(pempub)
        retval = rsa.verify(''.join(vdata).encode('utf8'), base64.b64decode(sig), pubkey)
        if retval == 'SHA-1':
            return {}
        load_pubkeys()
        pempub = web.config.vars.pubkeys.get(lid,{}).get('PUBKEY','')
        pubkey = rsa.PublicKey.load_pkcs1(pempub)
        retval = rsa.verify(''.join(vdata).encode('utf8'), base64.b64decode(sig), pubkey)
        return {} if retval == 'SHA-1' else {'errmsg': 'Invalid signature'}
    except Exception as e:
        try:
            load_pubkeys()
            pempub = web.config.vars.pubkeys.get(lid,{}).get('PUBKEY','')
            pubkey = rsa.PublicKey.load_pkcs1(pempub)
            retval = rsa.verify(''.join(vdata).encode('utf8'), base64.b64decode(sig), pubkey)
            return {} if retval == 'SHA-1' else {'errmsg': 'Invalid signature'}
        except Exception as e:
            traceback.print_exc()
            return {'errmsg': 'Invalid signature'}

def set_license_bind(lid, did, dname, sid, sname, surl, pexp, osname):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        count = web.listget(dbsl.select("DM_CLIENTS", what="COUNT(*) CNT", where="ISPRIMARY=1").list(),0,{}).get("CNT",0)
        pubpem, pripem = gen_rsakey()
        if web.listget(dbsl.select("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid").list(), 0, None):
            dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", DEVICEID=did, DEVICENAME=dname,
                SERVERID=sid, SERVERNAME=sname, SERVERURL=surl, PUBKEY=pubpem, OSNAME=osname, push_expire=(pexp or 0))
        else:
            ispri = 1 if count==0 else 0
            dbsl.insert("DM_CLIENTS", LICENSEID=lid, DEVICEID=did, DEVICENAME=dname, ISPRIMARY=ispri,
                SERVERID=sid, SERVERNAME=sname, SERVERURL=surl, PUBKEY=pubpem, OSNAME=osname, push_expire=(pexp or 0))
        dbsl.update("DM_CONFIG", vars=locals(), where="CKEY='ENABLE_BIND'", CVAL=0)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        load_pubkeys()
        return {"body": {"pem": pripem, "sid": sid, "sname": sname, "surl": surl, "lid": lid, "osname": osname}}

def relocate_license(lid, surl):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", SERVERURL=surl)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def del_license_bind(lid):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.delete("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid")
        if web.listget(dbsl.select("DM_CLIENTS", what="count(*) CNT").list(),0,{}).get('CNT',0) == 0:
            set_syskey('ENABLE_BIND', 1)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        web.config.vars.pubkeys.pop(lid,None)
        return {}

def list_devices():
    return (
        dbsl.select(
            "DM_CLIENTS",
            what="LICENSEID, SERVERID, SERVERNAME, SERVERURL, DEVICEID, DEVICENAME, ISPRIMARY",
        ).list()
        if dbsl
        else []
    )

def del_device(did, dlid):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.delete("DM_CLIENTS", vars=locals(), where="DEVICEID=$did AND LICENSEID=$dlid")
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        web.config.vars.pubkeys.pop(dlid,None)
        return {}

def get_serverinfo(lid):
    m = web.listget(dbsl.select("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid").list(),0,{})
    return (m.get("SERVERNAME"), m.get('code_server') or '', m.get('SERVERURL') or '')

def set_servername(lid, sname):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", SERVERNAME=sname)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def set_pushexpire(lid, pexp):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", push_expire=pexp)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        load_pubkeys()
        return {}

def set_codeserver(lid, curl):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", code_server=curl)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}


def load_alerts():
    from operator import itemgetter
    from itertools import groupby
    if not dbsl: return
    m = dbsl.select("DM_ALERTS", vars=locals(), where="ALENABLED=1", order="CNAME").list()
    llg = groupby([x for x in m if x.ALTYPE==1], itemgetter('CNAME'))
    lcm = groupby([x for x in m if x.ALTYPE in (2,3)], itemgetter('CNAME'))
    lph = groupby([x for x in m if x.ALTYPE in (4,5)], itemgetter('CNAME'))
    web.config.vars['alertlg'] = dict([(cname, list(val)) for cname, val in llg if cname=='--sys--' or mdocker.exists_container(cname)])
    web.config.vars['alertcm'] = dict([(cname, list(val)) for cname, val in lcm if cname=='--sys--' or mdocker.exists_container(cname)])
    web.config.vars['alertph'] = dict([(cname, list(val)) for cname, val in lph if cname=='--sys--' or mdocker.exists_container(cname)])

def insert_stats(cname, hdat):
    if not dbsl: return
    newdat = {
        "CNAME" : cname,
        "DATASTAMP" : hdat[0],
        "ST01" : hdat[1],
        "ST02" : hdat[2],
        "ST03" : hdat[3],
        "ST04" : hdat[4],
        "ST05" : hdat[5],
        "ST06" : hdat[6],
        "ST07" : hdat[7],
        "ST08" : hdat[8],
        "ST09" : hdat[9],
        "ST10" : hdat[10],
        "ST11" : hdat[11]
    }
    return dbsl.insert("DM_STATS", **newdat)

def list_alert(lid, cname):
    if not dbsl: return []
    swhere = "LICENSEID=$lid AND ALTYPE>0"
    if cname:
        swhere += " and CNAME=$cname"
    return dbsl.select(
        "DM_ALERTS",
        what="ALID,CNAME,ALTYPE,ALSTR,ALVAL,ALENABLED,ALPUSH,ALLEVEL",
        vars=locals(),
        where=swhere,
    ).list()

def chk_alert(params):
    if not params.lid: return {'errmsg': 'Invalid Client'}
    if not params.cname: return {'errmsg': 'Invalid Container'}
    if params.cname != '--sys--' and not mdocker.exists_container(params.cname): return {'errmsg': 'Invalid Container'}
    if not params.altype.isdigit(): return {'errmsg': 'Invalid Target'}
    if int(params.altype) not in (1,2,3,4,5): return {'errmsg': 'Invalid Target'}
    params.altype = int(params.altype)
    if params.altype == 1:
        pass
    elif params.altype == 2:
        if (
            not params.alval.isdigit()
            or int(params.alval) <= 0
            or int(params.alval) >= 100
        ):
            return {'errmsg': 'Invalid Value'}
    elif params.altype == 3:
        if not params.alval.isdigit() or int(params.alval) <= 0:
            return {'errmsg': 'Invalid Value'}
    elif params.altype == 4:
        ipport = params.alstr.split(":")
        if (
            len(ipport) != 2
            or not web.validipaddr(ipport[0])
            or not web.validipport(ipport[1])
        ):
            return {'errmsg': 'Invalid host:port'}
    elif params.altype == 5:
        if not params.alstr.lower().startswith(('http:','https:')):
            return {'errmsg': 'Invalid URL'}
    if params.enabled not in [1, "1"]: params.enabled = 0
    if params.push not in [1, "1"]: params.push = 0
    if not params.level.isdigit(): return {'errmsg': 'Invalid Level'}
    return {} if int(params.level) in {1, 2, 3} else {'errmsg': 'Invalid Level'}

def set_alert(params):
    if not dbsl: return {'errmsg': 'No database'}
    retval = chk_alert(params)
    if retval.get('errmsg'): return retval
    t = dbsl.transaction()
    try:
        if params.alid and web.listget(dbsl.select("DM_ALERTS", vars=locals(), where="ALID=$params.alid").list(), 0, None):
            dbsl.update("DM_ALERTS", vars=locals(), where="ALID=$params.alid",
                LICENSEID = params.lid,
                CNAME = params.cname,
                ALTYPE = params.altype,
                ALSTR = params.alstr,
                ALVAL = params.alval,
                ALENABLED = params.enabled,
                ALPUSH = params.push,
                ALLEVEL = params.level
            )
        else:
            dbsl.insert("DM_ALERTS",
                LICENSEID = params.lid,
                CNAME = params.cname,
                ALTYPE = params.altype,
                ALSTR = params.alstr,
                ALVAL = params.alval,
                ALENABLED = params.enabled,
                ALPUSH = params.push,
                ALLEVEL = params.level
            )
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        load_alerts()
        return {}

def del_alert(alid):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.delete("DM_MESSAGE", vars=locals(), where="ALID=$alid")
        dbsl.delete("DM_ALERTS", vars=locals(), where="ALID=$alid")
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        load_alerts()
        return {}


def count_message1(lid, cname=''):
    if not dbsl: return {}
    swhere = "A.ALID=M.ALID AND A.LICENSEID=$lid AND ISREAD<2"
    if cname:
        swhere += " AND A.CNAME=$cname"
    retval = dbsl.select("DM_ALERTS A, DM_MESSAGE M",
        what="A.CNAME, SUM(CASE ISREAD WHEN 0 THEN 1 ELSE 0 END) CNT1, count(MSGID) CNT2", vars=locals(),
        where=swhere, group="A.CNAME").list()
    return dict([(x.CNAME, (x.CNT1, x.CNT2)) for x in retval])

def list_newmsg(lid, cname):
    if not dbsl: return []
    swhere = "A.ALID=M.ALID and A.LICENSEID=$lid and M.ISREAD=0"
    if cname:
        swhere += " AND A.CNAME=$cname"
    return dbsl.select(
        "DM_ALERTS A, DM_MESSAGE M",
        what="A.ALID,A.CNAME,ALTYPE,ALLEVEL,MSGID,MSGSTAMP,ISREAD,ISPUSHED,MSGKEYWORD,MSGBODY,MSGURL",
        vars=locals(),
        where=swhere,
        order="M.MSGID desc",
    ).list()

def count_message2(lid, cname, skey=''):
    if not dbsl: return []
    swhere = "A.ALID=M.ALID and A.LICENSEID=$lid"
    if cname:
        swhere += " AND A.CNAME=$cname"
    if skey:
        skey = f'%{skey}%'
        swhere += " AND MSGBODY like $skey"
    return web.listget(dbsl.select("DM_ALERTS A, DM_MESSAGE M", what="COUNT(MSGID) CNT",vars=locals(), where=swhere).list(),0,{}).get('CNT',0)

def list_message(lid, cname, alid='', skey='', isrd='', offset=0, limit=20):
    if not dbsl: return []
    swhere = "A.ALID=M.ALID and A.LICENSEID=$lid"
    if cname:
        swhere += " AND A.CNAME=$cname"
    if alid:
        swhere += " AND A.ALID=$alid"
    if skey:
        skey = f'%{skey}%'
        swhere += " AND (MSGBODY like $skey or datetime(MSGSTAMP, 'unixepoch', 'localtime') like $skey)"
    if isrd:
        swhere += " AND ISREAD<2"
    return dbsl.select(
        "DM_ALERTS A, DM_MESSAGE M",
        what="A.ALID,A.CNAME,ALTYPE,ALLEVEL,MSGID,MSGSTAMP,ISREAD,ISPUSHED,MSGKEYWORD,MSGBODY,MSGURL",
        vars=locals(),
        where=swhere,
        order="ISREAD, M.MSGID desc",
        offset=offset,
        limit=limit,
    ).list()

def new_message(data):
    if not dbsl: return {'errmsg': 'No database'}
    data["MSGSTAMP"] = data.get("MSGSTAMP") or time.time()
    data["ISREAD"] = 0
    t = dbsl.transaction()
    try:
        msgid = dbsl.insert("DM_MESSAGE", **data)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {'MSGID':msgid}

def get_message(msgid):
    return (
        web.listget(
            dbsl.select(
                "DM_ALERTS A, DM_MESSAGE M",
                what="A.ALID,A.CNAME,ALTYPE,ALLEVEL,MSGID,MSGSTAMP,ISREAD,ISPUSHED,MSGKEYWORD,MSGBODY,MSGURL",
                vars=locals(),
                where="A.ALID=M.ALID AND M.MSGID=$msgid",
            ).list(),
            0,
            {},
        )
        if dbsl
        else {'errmsg': 'No database'}
    )

def set_message(msgid, isread):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_MESSAGE", vars=locals(), where="MSGID=$msgid", ISREAD=isread)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def del_message(msgid):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.delete("DM_MESSAGE", vars=locals(), where="MSGID=$msgid")
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}


def get_noti(lid):
    return web.listget(dbsl.select("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", what="EXNOTIISON, EXNOTIPASS").list(), 0, {})
def set_noti(lid, ison, pkey):
    if not dbsl: return {'errmsg': 'No database'}
    lobj = web.config.vars.pubkeys.get(lid)
    if not lobj: return {'errmsg': 'No such client'}
    if lobj.get('push_expire',0)<=time.time(): return {'errmsg': 'License/Push service expired'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_CLIENTS", vars=locals(), where="LICENSEID=$lid", EXNOTIISON=ison, EXNOTIPASS=pkey)
        lobj['EXNOTIISON'] = ison
        lobj['EXNOTIPASS'] = pkey
        web.config.vars.pubkeys[lid] = lobj
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def push_message(lid, pkey, data):
    if not dbsl: return {'errmsg': 'No database'}
    lobj = web.config.vars.pubkeys.get(lid)
    if not lobj:
        load_pubkeys()
        lobj = web.config.vars.pubkeys.get(lid)
    if not lobj: return {'errmsg': 'License not exists'}
    if not lobj.get('EXNOTIISON'):
        load_pubkeys()
        lobj = web.config.vars.pubkeys.get(lid)
    if not lobj.get('EXNOTIISON'): return {'errmsg': 'External notification is off'}
    if not pkey or (pkey and lobj.get('EXNOTIPASS')!=pkey): return {'errmsg': 'Require password to send external notification'}
    if not data.get('body'): return {'errmsg': 'body required'}
    if f"{data.get('level', '')}" not in ('1', '2', '3'): data['level'] = 1
    from . import apush
    try:
        aobj = web.listget(dbsl.select("DM_ALERTS", vars=locals(), where="LICENSEID=$lid and CNAME='--sys--' and ALTYPE=0 and ALENABLED=0").list(), 0, None)
        alid = (
            aobj.ALID
            if aobj
            else dbsl.insert(
                "DM_ALERTS",
                ALSTR='',
                ALVAL='',
                ALPUSH=1,
                LICENSEID=lid,
                CNAME='--sys--',
                ALTYPE=0,
                ALENABLED=0,
                ALLEVEL=data.get('level', 1),
            )
        )
        msgid = dbsl.insert("DM_MESSAGE",
            ALID        = alid,
            MSGSTAMP    = time.time(),
            ISREAD      = 0,
            ISPUSHED    = 1,
            MSGKEYWORD  = data.get('title',''),
            MSGBODY     = data.get('body',''),
            MSGURL      = data.get('url', '')
        )
        if lobj.get('push_expire',0)<=time.time():
            load_pubkeys()
            lobj = web.config.vars.pubkeys.get(lid)
        if lobj.get('push_expire',0)<=time.time():
            return {'errmsg': 'License/Push service expired'}
        retval = apush.pushNotification(
            lobj.get('LICENSEID', ''),
            lobj.get('SERVERID', ''),
            lobj.get('DEVICEID', ''),
            data.get('title', ''),
            data.get('body', ''),
            f'domapp://message/{msgid}?lid={lid}',
        )
        retval = formator.json_object(retval)
        return retval
    except Exception as e:
        return {'errmsg': str(e)}



def list_compose():
    return dbsl.select("DM_COMPOSE").list() if dbsl else []

def add_compose(fpath):
    if not dbsl: return {'errmsg': 'No database'}
    realpath = fpath if os.path.isabs(fpath) else utils.prefixStorageDir(fpath)
    if not os.path.isfile(realpath):
        return {'errmsg': f'File {fpath} not exists'}
    folder = os.path.split(os.path.abspath(realpath))[0]
    if web.listget(dbsl.select("DM_COMPOSE", vars=locals(), where="FILEPATH=$fpath and FOLDER=$folder").list(),0):
        return {"errmsg": f"{fpath} already exists"}
    alias = (
        os.path.basename(os.path.split(fpath)[0])
        if fpath.lower().endswith(('yaml', 'yml'))
        else os.path.basename(fpath)
    )
    t = dbsl.transaction()
    try:
        dbsl.insert("DM_COMPOSE", ALIAS=alias, FILEPATH=fpath, FOLDER=folder)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def get_compose(cmpsid):
    if not dbsl: return
    return web.listget(
        dbsl.select(
            "DM_COMPOSE", vars=locals(), where="CMPSID=$cmpsid"
        ).list(),
        0,
    )

def set_compose(cmpsid, alias):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.update("DM_COMPOSE", vars=locals(), where="CMPSID=$cmpsid", ALIAS=alias)
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

def del_compose(cmpsid):
    if not dbsl: return {'errmsg': 'No database'}
    t = dbsl.transaction()
    try:
        dbsl.delete("DM_COMPOSE", vars=locals(), where="CMPSID=$cmpsid")
    except Exception as e:
        t.rollback()
        traceback.print_exc()
        return {"errmsg":e}
    else:
        t.commit()
        return {}

