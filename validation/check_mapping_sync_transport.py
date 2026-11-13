from pathlib import Path
import sys, json, base64
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from github_store import GitHubVault, GitHubConfig
from mapping_sync import MappingRepository, make_plan, synchronize
from security import generate_key, seal_vault, open_vault
from models import new_vault, new_sheet
from cryptography.fernet import Fernet

class Response:
 def __init__(self,status,data): self.status_code,self.data,self.headers=status,data,{}
 def json(self): return deepcopy(self.data)
class Service:
 def __init__(self,n,key,fail_backup=False,fail_save=False):
  self.key=key; self.value=new_vault(); self.sha='sha1'; self.calls=[]; self.backups=[]; self.writes=0
  self.fail_backup=fail_backup; self.fail_save=fail_save
  sheet=new_sheet('P4102'); sheet['fields']['Diagnoses']='SYNTHETIC_PRIVATE_'+str(n)
  self.value['rooms']['P4102']=sheet
  self.value['settings']['medication_mappings']=[dict(name='synthetic med '+str(n),match='prefix',destination='Respiratory')]
 def request(self,method,url,**kwargs):
  self.calls.append((method,url))
  if '/branches/' in url: return Response(200,{'name':'main'})
  if '/contents/' not in url: return Response(200,{'private':True,'archived':False})
  if method=='GET': return Response(200,{'type':'file','encoding':'base64','sha':self.sha,'content':base64.b64encode(seal_vault(self.value,self.key)).decode()})
  body=kwargs['json']
  if '/mapping-sync-backups/' in url:
   if self.fail_backup: return Response(403,{'message':'SECRET_MUST_NOT_LEAK'})
   self.backups.append(json.loads(Fernet(self.key.encode()).decrypt(base64.b64decode(body['content']))))
   return Response(201,{'content':{'sha':'backupsha'}})
  if self.fail_save: return Response(409,{'message':'SECRET_MUST_NOT_LEAK'})
  assert body['sha']==self.sha
  self.value=open_vault(base64.b64decode(body['content']),self.key); self.sha+='x'; self.writes+=1
  return Response(200,{'content':{'sha':self.sha}})

report=[]
for scenario in ('success','backup_denial','concurrent_save'):
 key=generate_key()
 services=[Service(n,key,fail_backup=(scenario=='backup_denial' and n==2),fail_save=(scenario=='concurrent_save' and n==2)) for n in (1,2,3)]
 repos=[MappingRepository('App '+str(n),GitHubVault(GitHubConfig('synthetic-token','synthetic/data'+str(n)),key,session=service)) for n,service in enumerate(services,1)]
 before=[deepcopy(s.value['rooms']) for s in services]
 snapshots=[r.snapshot() for r in repos]
 plan=make_plan(snapshots)
 result=synchronize(repos,plan,plan.resolve(),lambda:True)
 assert [s.value['rooms'] for s in services]==before
 assert all('SYNTHETIC_PRIVATE' not in json.dumps(b) for s in services for b in s.backups)
 assert 'SECRET_MUST_NOT_LEAK' not in repr(result)
 if scenario=='success':
  assert result.complete and all(s.writes==1 for s in services)
  assert all(len(s.value['settings']['medication_mappings'])==3 for s in services)
 elif scenario=='backup_denial':
  assert not result.complete and all(s.writes==0 for s in services)
  assert result.rows[1]['Code']=='ACCESS_FORBIDDEN'
 else:
  assert not result.complete and [s.writes for s in services]==[1,0,0]
  assert result.rows[1]['Code']=='SAVE_CONFLICT'
 report.append({'scenario':scenario,'passed':True,'writes':[s.writes for s in services]})
print(json.dumps(report,indent=2))
