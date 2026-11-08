"""Report fixed Wine defaults and counts only in the isolated signed-runtime QA prefix."""
import re

def read(path):
    sections={};key=None
    for line in path.read_text().splitlines():
        if line.startswith('[') and ']' in line:
            key=line[1:line.index(']')].replace('\\\\','\\').lower();sections.setdefault(key,{})
        elif key is not None:
            m=re.match(r'(?:"([^"=]*)"|(@))=(.*)$',line)
            if m:
                keyname=(m[1] or m[2]).lower();sections[key][keyname]=m[3].lower().replace('\\\\','\\')
    return sections

def observe(prefix):
    result={};current=r'software\microsoft\windows\currentversion';session=r'system\currentcontrolset\control\session manager';choices=current+r'\explorer\fileexts';explorer=current+r'\explorer';url=r'software\microsoft\windows\shell\associations\urlassociations';
    files={n:read(prefix/(n+'.reg')) for n in ('system','user','userdef')}
    for hive,data in files.items():
        vals={}
        for ending in ('run','runonce','runservices','runservicesonce'):
            rows=data.get(current+'\\'+ending,{});vals[ending]={'count':len(rows),'onlyWineMenubuilder':set(rows)=={'winemenubuilder'} and 'winemenubuilder.exe -a -r' in rows['winemenubuilder']}
        for suffix in ('shell folders','user shell folders'):
            startup=data.get(explorer+'\\'+suffix,{}).get('startup');v=(startup or '').strip('"')
            vals[suffix.replace(' ','')+'Startup']={'present':bool(startup),'standardRelative':v.endswith(r'\start menu\programs\startup'),'standardUserRoot':bool(re.fullmatch(r'c:\\users\\[^\\]+\\(?:appdata\\roaming\\microsoft\\windows\\)?start menu\\programs\\startup',v)),'usesUserProfile':v.startswith('%userprofile%'),'typeExpand':v.startswith('str(2):')}
        vals['pendingRenameCount']=sum(int('pendingfilerenameoperations' in rows) for k,rows in data.items() if k==session or re.fullmatch(r'system\\controlset\d{3}\\control\\session manager',k))
        vals['userChoice']={}
        for scheme in ('ftp','http','https'):
            values=data.get(url+'\\'+scheme+r'\userchoice',{});value=values.get('progid');vals['userChoice'][scheme]={'count':len(values),'hasProgId':value is not None,'usesOwnScheme':value in ('"'+scheme+'"','"'+scheme+'file"')}
        vals['navigatingEmptyDefaults']=sum(1 for k,v in data.items() if k.endswith(r'\navigating\.current') and v.get('@')=='""');vals['navigatingNonemptyDefaults']=sum(1 for k,v in data.items() if k.endswith(r'\navigating\.current') and v.get('@') not in (None,'""'))
        vals['directXInstalledVersionExpected']=data.get(r'software\microsoft\directx',{}).get('installedversion')=='hex:00,00,00,09,00,00,00,00';vals['aeDebugAutoExpected']=data.get(r'software\microsoft\windows nt\currentversion\aedebug',{}).get('auto')=='"1"'
        result[hive]={'bytes':(prefix/(hive+'.reg')).stat().st_size,'defaults':vals}
    return result
