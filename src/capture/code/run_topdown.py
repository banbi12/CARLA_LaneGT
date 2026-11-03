"""Reuse Epic startup, RPC-ready handshake and owned-process memory guard; one map per attempt."""
import os,sys,json,argparse,subprocess,time,shutil,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'code'))
import legacy_supervisor as base
from resource_guard import MemoryWatch,stop_owned,MIB
from mapgt.common import load,save,require

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['selective','restart_check'],required=True);ap.add_argument('--attempt',type=int,default=1);args=ap.parse_args()
 cases=load(R/'cases.json')
 selected=[load(R/'evidence/calibration_case.json')] if args.stage=='restart_check' else cases
 root=R/'runtime'/('capture_'+args.stage+('' if args.attempt==1 else '_attempt'+str(args.attempt)));root.mkdir(exist_ok=False)
 for name in ('runtime','logs','config','tmp','cache'):(root/name).mkdir()
 shutil.copy2(R/'config/DefaultEngine.source.ini',root/'config/DefaultEngine.source.ini')
 base.RUN=root;base.PORT=2070
 require(not base.existing_servers(),'DO_NOT_INTERFERE_WITH_EXISTING_SERVER');require(base.ports_free(),'PORTS_BUSY');require(base.memory_available()>7*1024**3,'HOST_RAM')
 watch=MemoryWatch(root,7057*MIB,.1);processes=[];logs=[];summary=dict(stage=args.stage,cases=[c['case_id'] for c in selected],status='starting',quality='Epic',requested_limit_MB=7400,trigger_mib=7057)
 try:
  watch.start();idle=watch.samples[-1]['used_bytes'];(root/'runtime/Town10HD_Opt').mkdir();userdir=base.user_settings('Town10HD_Opt');env=base.child_environment()
  command=['/usr/bin/stdbuf','-oL','-eL',str(base.BINARY),'CarlaUE4','/Game/Carla/Maps/Town10HD_Opt','-RenderOffScreen','-quality-level=Epic','-carla-rpc-port=2070','-carla-streaming-port=2071','-carla-secondary-port=2072','-ResX=640','-ResY=360','-windowed','-nosound','-unattended','-novsync','-stdout','-FullStdOutLogOutput','-FORCELOGFLUSH','-RPCThreads=2','-StreamingThreads=2','-SecondaryThreads=2','-LogCmds=LogCarla VeryVerbose,LogConsoleResponse VeryVerbose','-ExecCmds=sg.ViewDistanceQuality,sg.ShadowQuality,sg.PostProcessQuality,sg.TextureQuality,sg.EffectsQuality,sg.FoliageQuality','-UserDir='+str(userdir),'-abslog='+str(root/'logs/Town10HD_Opt_server.engine.log')]
  save(root/'runtime/Town10HD_Opt/server_command.json',dict(argv=command,cwd=str(base.CARLA)))
  log=(root/'logs/Town10HD_Opt_server.stdout.log').open('x');logs.append(log);watch.set_phase(args.stage+':server_startup')
  server=subprocess.Popen(command,cwd=str(base.CARLA),env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);processes.append((server,'CARLA_server'));watch.track(server,'CARLA_server');print('START_EPIC',args.stage,server.pid,flush=True)
  base.wait_rpc_listener(server,watch,120)
  childlog=(root/'logs/capture.log').open('x');logs.append(childlog);watch.set_phase(args.stage+':capture')
  childfile=R/'code/capture_selective.py'
  childcmd=[str(base.PYTHON),'-B','-u',str(childfile),'--port','2070','--cases',','.join(c['case_id'] for c in selected)]
  if args.stage=='restart_check':childcmd.append('--verify-restart')
  save(root/'runtime/capture_command.json',dict(argv=childcmd))
  child=subprocess.Popen(childcmd,cwd=str(R),env=env,stdout=childlog,stderr=subprocess.STDOUT,start_new_session=True);processes.append((child,'topdown_child'));watch.track(child,'topdown_child')
  base.wait_child(child,'topdown_capture',watch,86400,server)
  summary['quality_proof']=base.quality_proof('Town10HD_Opt',root/'logs/Town10HD_Opt_server.stdout.log');summary['status']='captured'
 except BaseException as e:summary.update(status='failed',error=repr(e),traceback=traceback.format_exc());print('CAPTURE_ABORT',repr(e),flush=True)
 finally:
  watch.set_phase(args.stage+':cleanup')
  for p,label in reversed(processes):stop_owned(p,label,watch.events)
  try:
   if watch.samples and not watch.error:base.wait_released(watch,idle,45)
  except Exception as e:summary['cleanup_error']=str(e)
  summary['gpu_monitor']=watch.close();summary['all_owned_processes_exited']=all(p.poll() is not None for p,_ in processes);summary['unrelated_processes_signaled']=False
  for log in logs:log.close()
  save(root/'summary.json',summary)
 print(json.dumps(summary,ensure_ascii=False),flush=True)
 if summary['status']!='captured':raise SystemExit(2)
if __name__=='__main__':main()
