#!/usr/bin/env python
#-*- encoding: utf-8 -*-


from config import *
from . import mdb, mdocker

dclient = variant.dclient

def callShell(cmd):
    import subprocess,traceback,platform
    try:
        p = subprocess.Popen(args=cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (stdoutput,erroutput) = p.communicate()
        retval = stdoutput
    except Exception as e:
        traceback.print_exc()
        retval = ''
    if platform.system()=='Windows':
        retval = unicode(retval, 'gbk')
    return retval.strip().decode('utf8')


def execShell(cmd):
    from subprocess import check_output
    out = check_output(cmd.split(' '), universal_newlines=True)

def iterateShellCall(cmd):
    import subprocess, io
    proc = subprocess.Popen(args=cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    yield from io.TextIOWrapper(proc.stdout, encoding="utf-8")

def iterateTest(count):
    for x in range(1,count):
        yield f"{x}"
        time.sleep(0.5)


def escape_ansi1(value):
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', value)

def escape_ansi2(line):
    import re
    ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', line)

def escape_ansi3(somebytesvalue):
    ansi_escape_8bit = re.compile(
        br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])'
    )
    return ansi_escape_8bit.sub(b'', somebytesvalue)

def get_mac_address():
    import uuid
    mac = uuid.UUID(int = uuid.getnode()).hex[-12:]
    return ":".join([mac[e:e+2] for e in range(0,11,2)])

def get_selfcontainer():
    macadr = get_mac_address()
    for cobj in dclient.api.containers():
        cmac = ''
        if cobj['HostConfig']['NetworkMode'] in cobj['NetworkSettings']['Networks']:
            cmac = cobj['NetworkSettings']['Networks'][cobj['HostConfig']['NetworkMode']]['MacAddress']
        elif 'bridge' in cobj['NetworkSettings']['Networks']:
            cmac = cobj['NetworkSettings']['Networks']['bridge']['MacAddress']
        if cmac and cmac==macadr:
            return cobj
    return {}

def list_files(folder):
    import platform
    retval = []
    if variant.inside_container and not folder:
        cobj = get_selfcontainer()
        for item in cobj.get('Mounts',[]):
            n = item['Destination']
            if not n.endswith('docker.sock') and (platform.system().lower()!='windows' and not n.startswith('.')):
                if os.path.isdir(n):
                    retval.append([n, 'd'])
                elif os.path.isfile(n):
                    retval.append([n, 'f'])
        return retval
    elif not os.path.isabs(folder) or folder=='':
        folder = utils.prefixStorageDir(folder)
    for n in os.listdir(folder):
        if not n.endswith('docker.sock') and (platform.system().lower()!='windows' and not n.startswith('.')):
            if os.path.isdir(os.path.join(folder,n)):
                retval.append([n, 'd'])
            elif os.path.isfile(os.path.join(folder,n)):
                retval.append([n, 'f'])
    retval.sort()
    return retval

COMPOSE_HINT = '''docker-compose is running in a Mildred container. docker-compose up could fail in some cases because it's in a container.\n
* Please pay attention to the configuration of docker-compose.yml, eg: volumes.'''

def compose_info():
    version = callShell('docker-compose version')
    version = version.split(',')[0].replace('docker-compose version','').strip()
    return [version, COMPOSE_HINT if variant.inside_container else '']

def compose_images(fname):
    retval = []
    if not os.path.isfile(fname): return retval
    if not fname.lower().endswith(('.yaml','.yml')): return retval
    retdat = callShell(f'docker-compose -f {fname} --no-ansi images -q')
    iids = [y for x in retdat.split('\r\n') for y in x.split('\n')]
    try:
        retdic = mdocker.tree_image()
        for imgid in iids:
            if iobj := retdic.get(imgid) or retdic.get(f'sha256:{imgid}'):
                retval.append(iobj)
    except Exception as e:
        pass
    return retval

def compose_containers(fname):
    retval = []
    if not os.path.isfile(fname): return retval
    if not fname.lower().endswith(('.yaml','.yml')): return retval
    retdat = callShell(f'docker-compose -f {fname} --no-ansi ps -q')
    cids = [y for x in retdat.split('\r\n') for y in x.split('\n')]
    try:
        retval = [mdocker.dict_container(x) for x in dclient.api.containers(all=True) if x["Id"] in cids]
    except Exception as e:
        pass
    return retval


def compose_filebody(fname):
    retval = "File not exists"
    if os.path.isfile(fname):
        with open(fname) as fobj:
            retval = fobj.read()
    return retval

def compose_test(count):
    return iterateTest(count)

def compose_up(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi up -d')

def compose_down(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi down')

def compose_start(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi start')

def compose_stop(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi stop')

def compose_restart(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi restart')

def compose_remove(fname):
    return iterateShellCall(f'docker-compose -f {fname} --no-ansi rm -f')


