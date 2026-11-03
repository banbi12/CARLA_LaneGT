"""Bounded Epic image collection: one native six-camera group per standard town."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import configparser
import socket
import subprocess
import sys
import time
import traceback

from resource_guard import MemoryWatch,stop_owned,MIB

RUN=Path(__file__).resolve().parents[1]
RUNTIME_PATHS=json.loads((RUN/'config/runtime_paths.json').read_text())
PYTHON=Path(RUNTIME_PATHS['carla_python'])
CARLA=Path(RUNTIME_PATHS['carla_root'])
BINARY=CARLA/"CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping"
PORT=2000

def save(path,value):
    path=Path(path)
    with path.open("x") as f:json.dump(value,f,ensure_ascii=False,allow_nan=False,indent=2)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def assert_frozen():
    record=json.loads((RUN/"evidence/code_fingerprints.json").read_text())
    for p,h in record["files"].items():
        if sha(p)!=h:raise ValueError("Frozen file changed: "+p)
    sources=json.loads((RUN/"evidence/source_baseline.json").read_text())
    for ref in sources["protected_sources"]:
        p=Path(ref["path"])
        if sha(p)!=ref["sha256"] or p.stat().st_mtime_ns!=ref["mtime_ns"]:
            raise ValueError("Protected collector/source changed: "+str(p))

def ports_free():
    for port in [PORT,PORT+1,PORT+2,PORT+50]:
        sock=socket.socket()
        try:sock.bind(("127.0.0.1",port))
        except OSError:return False
        finally:sock.close()
    return True

def memory_available():
    return int(next(x.split()[1] for x in Path("/proc/meminfo").read_text().splitlines() if x.startswith("MemAvailable:")))*1024

def existing_servers():
    output=subprocess.check_output(["ps","-eo","pid,comm"],text=True)
    return [line.strip() for line in output.splitlines() if "CarlaUE4" in line]

def child_environment():
    env=dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1",OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",
        TMPDIR=str(RUN/"tmp"),XDG_CONFIG_HOME=str(RUN/"cache/xdg_config"),XDG_CACHE_HOME=str(RUN/"cache/xdg_cache"),
        XDG_DATA_HOME=str(RUN/"cache/xdg_data"),CUDA_CACHE_PATH=str(RUN/"cache/cuda"),
        __GL_SHADER_DISK_CACHE_PATH=str(RUN/"cache/nvidia"),MESA_SHADER_CACHE_DIR=str(RUN/"cache/mesa"))
    env.update(VK_DRIVER_FILES="/usr/share/vulkan/icd.d/nvidia_icd.json",VK_ICD_FILENAMES="/usr/share/vulkan/icd.d/nvidia_icd.json",__NV_PRIME_RENDER_OFFLOAD="1",__VK_LAYER_NV_optimus="NVIDIA_only",__GLX_VENDOR_LIBRARY_NAME="nvidia")
    return env

def wait_child(proc,label,watch,deadline_s,server_proc=None):
    end=time.monotonic()+deadline_s;last=time.monotonic()
    while proc.poll() is None:
        watch.check()
        if server_proc is not None and server_proc.poll() is not None:raise RuntimeError("Owned CARLA server exited before "+label)
        if time.monotonic()>end:raise TimeoutError(label+" deadline exceeded")
        if time.monotonic()-last>15:
            last=time.monotonic()
            used=watch.samples[-1]["used_mib"] if watch.samples else -1
            print(label+" running; sampled card %.1f MiB"%used,flush=True)
        time.sleep(.1)
    watch.check()
    if proc.returncode!=0:raise RuntimeError(label+" failed, exit "+str(proc.returncode))

def wait_rpc_listener(server,watch,timeout=120):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        watch.check()
        if server.poll() is not None:raise RuntimeError("Server exited before RPC readiness")
        try:
            with socket.create_connection(("127.0.0.1",PORT),timeout=.5):pass
            print("RPC listener ready; creating Python probe next",flush=True)
            for _ in range(20):watch.check();time.sleep(.1)
            return
        except OSError:time.sleep(.2)
    raise TimeoutError("RPC listener readiness deadline")

def wait_released(watch,baseline,timeout=40):
    end=time.monotonic()+timeout;stable=None
    while time.monotonic()<end:
        watch.check()
        if watch.samples and watch.samples[-1]["used_bytes"]<=baseline+128*MIB and ports_free():
            stable=stable or time.monotonic()
            if time.monotonic()-stable>=3:return
        else:stable=None
        time.sleep(.1)
    raise TimeoutError("GPU/ports did not return to idle; next map prohibited")

def user_settings(map_name):
    root=RUN/"runtime"/map_name/"user"
    config=root/"Saved/Config/LinuxNoEditor";config.mkdir(parents=True)
    # Per-run generated config overrides the packaged default map without editing the installation.
    original=(RUN/"config/DefaultEngine.source.ini").read_text()
    content=re.sub(r"(?m)^(EditorStartupMap|GameDefaultMap|ServerDefaultMap|TransitionMap)=.*$",lambda m:m.group(1)+"=/Game/Carla/Maps/"+map_name+"."+map_name,original)
    with (config/"Engine.ini").open("x") as stream:stream.write(content)
    groups=["ViewDistance","AntiAliasing","Shadow","PostProcess","Texture","Effects","Foliage","Shading"]
    (config/"GameUserSettings.ini").write_text("[ScalabilityGroups]\nsg.ResolutionQuality=100.000000\n"+
        "".join("sg."+name+"Quality=3\n" for name in groups)+
        "\n[/Script/Engine.GameUserSettings]\nbUseVSync=False\nResolutionSizeX=640\nResolutionSizeY=360\nFullscreenMode=2\nVersion=5\n")
    return root

def quality_proof(map_name,log_path):
    text=log_path.read_text(errors="replace")
    matches=[line for line in text.splitlines() if re.search(r"Quality\s*Level\s*=.*Epic",line,re.I)]
    fallback=None
    if not matches:
        command=json.loads((RUN/"runtime"/map_name/"server_command.json").read_text())["argv"]
        cfg=configparser.ConfigParser();cfg.read(RUN/"runtime"/map_name/"user/Saved/Config/LinuxNoEditor/GameUserSettings.ini")
        values=dict(cfg["ScalabilityGroups"])
        if "-quality-level=Epic" not in command or any(values.get("sg."+name.lower()+"quality")!="3" for name in ("ViewDistance","AntiAliasing","Shadow","PostProcess","Texture","Effects","Foliage","Shading")):
            raise ValueError("Missing Epic startup/config evidence")
        fallback=dict(type="shipping_info_log_unavailable",actual_command_Epic=True,persisted_scalability=values,limitation="Quality enum not independently exposed by CARLA Python API; exact startup flag and persisted engine configuration recorded")
    wrong=[line for line in text.splitlines() if re.search(r"Quality\s*Level\s*=.*Low",line,re.I)]
    if wrong:raise ValueError("Server reported Low quality")
    return dict(command_quality="Epic",server_log_quality_lines=matches[-4:],alternate_quality_evidence=fallback,
                user_config=str(RUN/"runtime"/map_name/"user/Saved/Config/LinuxNoEditor/GameUserSettings.ini"),
                no_extra_scalability_or_resolution_fallback=True)

def report(summary):
    rows=[]
    for name,item in summary["maps"].items():
        rows.append("| "+name+" | "+item["status"]+" | "+str(item.get("images",0))+" | "+str(item.get("sampled_peak_used_mib","-"))+" |")
    text="# nuCarla exact-layout Epic camera collection test\n\n"
    text+="Requested maps: Town01-Town07 and Town10HD, one six-camera group each; no Opt duplicates, no added traffic.\n\n"
    text+="Status: "+summary["status"]+"\n\n"
    text+="| Map | Status | Images | Sampled peak card MiB |\n|---|---|---:|---:|\n"+"\n".join(rows)+"\n\n"
    text+="The requested 7400 MB decimal limit is conservatively represented by 7057 MiB (7399800832 bytes). NVML samples every 100 ms before startup, during rendering and during server teardown. A sampled stop is not a GPU hardware allocation cap.\n\n"
    text+="Each map starts a new owned CARLA server and exits it before the next. No hot client.load_world call; memory/ports must return to the initial idle range for three seconds. Only owned process groups may be terminated.\n\n"
    text+="Camera order/geometry follow actual nuCarla calibrated_sensor records (1600x900, FOV65). A new runtime adapter fixes the original quaternion-to-CARLA Euler discrepancy using explicit matrix basis changes; source collector files are unchanged. Measured image.transform plus same-frame ego pose validate every saved view, with 1 mm / 0.02 deg tolerances and original K.\n\n"
    text+="All new scripts/config/logs/images are in this run. Original BEVcollector and unaccepted MapTRv2_collector remain unchanged. No map training labels, MapTR/FastBEV inference, training, or Fusion work was performed. XODR is saved only as raw map context.\n\n"
    text+="See plan.json, runtime/gpu_memory.csv, runtime/gpu_monitor_summary.json, reports/*_validation.json and reports/*_six_cams.png. Failed/remaining maps are not presented as completed.\n"
    if summary.get("error"):text+="\nFailure: "+summary["error"]+"\n"
    (RUN/"reports/REPORT.md").write_text(text)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--execute-capture",action="store_true");a=p.parse_args()
    if not a.execute_capture:raise ValueError("Explicit execution flag required")
    if (RUN/"runtime/sequence_started.json").exists():raise FileExistsError("Do not overwrite/replay this attempt")
    plan=json.loads((RUN/"plan.json").read_text())
    assert_frozen()
    if json.loads((RUN/"evidence/CPU_and_guard_preflight.json").read_text())["status"]!="passed":raise RuntimeError("CPU preflight missing")
    if existing_servers():raise RuntimeError("Existing CARLA server found; will not interfere")
    if not ports_free():raise RuntimeError("Dedicated ports are not free")
    if memory_available()<7*1024**3:raise RuntimeError("Need at least 7GiB free host RAM")
    if shutil.disk_usage(RUN).free<2*1024**3:raise RuntimeError("Need at least 2GiB free output disk")
    watch=MemoryWatch(RUN,plan["trigger_mib"]*MIB,.1)
    processes=[];opened=[];summary=dict(status="started",run=str(RUN),maps={n:dict(status="not_started") for n in plan["maps"]},
        requested_maps=plan["maps"],requested_limit_MB=7400,effective_limit_mib=plan["trigger_mib"],model_inference=False,training=False)
    started=time.monotonic();server=None;child=None;current=None
    try:
        watch.start();baseline=watch.samples[-1]["used_bytes"]
        save(RUN/"runtime/sequence_started.json",dict(plan_sha256=sha(RUN/"plan.json"),baseline_memory=watch.samples[-1],
            dedicated_rpc_port=PORT,existing_carLA_servers=[],host_mem_available_bytes=memory_available(),
            data_disk_free_bytes=shutil.disk_usage(RUN).free))
        env=child_environment()
        for name in plan["maps"]:
            assert_frozen();watch.check();current=name
            if not ports_free():raise RuntimeError("Ports not free before "+name)
            root=RUN/"runtime"/name;root.mkdir()
            userdir=user_settings(name)
            args=["/usr/bin/stdbuf","-oL","-eL",str(BINARY),"CarlaUE4","/Game/Carla/Maps/"+name,"-RenderOffScreen","-quality-level=Epic",
                  "-carla-rpc-port="+str(PORT),"-carla-streaming-port="+str(PORT+1),"-carla-secondary-port="+str(PORT+2),
                  "-ResX=640","-ResY=360","-windowed","-nosound","-unattended","-novsync","-stdout","-FullStdOutLogOutput","-FORCELOGFLUSH","-RPCThreads=2","-StreamingThreads=2","-SecondaryThreads=2","-LogCmds=LogCarla VeryVerbose,LogConsoleResponse VeryVerbose","-ExecCmds=sg.ViewDistanceQuality,sg.ShadowQuality,sg.PostProcessQuality,sg.TextureQuality,sg.EffectsQuality,sg.FoliageQuality",
                  "-UserDir="+str(userdir),"-abslog="+str(RUN/"logs"/(name+"_server.engine.log"))]
            log_path=RUN/"logs"/(name+"_server.stdout.log")
            logfile=log_path.open("x");opened.append(logfile)
            start_sample=len(watch.samples);watch.set_phase(name+":server_startup")
            print(name+" starting new Epic server",flush=True)
            server=subprocess.Popen(args,cwd=str(CARLA),env=env,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((server,name+":server"));watch.track(server,name+":server")
            save(root/"server_command.json",dict(argv=args,cwd=str(CARLA),pid=server.pid,environment_overrides={k:env[k] for k in ["TMPDIR","XDG_CONFIG_HOME","XDG_CACHE_HOME","XDG_DATA_HOME","CUDA_CACHE_PATH","__GL_SHADER_DISK_CACHE_PATH","MESA_SHADER_CACHE_DIR","VK_DRIVER_FILES","VK_ICD_FILENAMES","__NV_PRIME_RENDER_OFFLOAD","__VK_LAYER_NV_optimus","__GLX_VENDOR_LIBRARY_NAME"]}))
            wait_rpc_listener(server,watch)
            probe_cmd=[str(PYTHON),"-B",str(RUN/"code/rig_capture.py"),"probe","--map",name,"--port",str(PORT)]
            probe_log=(RUN/"logs"/(name+"_probe.log")).open("x");opened.append(probe_log)
            child=subprocess.Popen(probe_cmd,cwd=str(RUN),env=env,stdout=probe_log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((child,name+":probe"));watch.track(child,name+":probe")
            wait_child(child,name+":probe",watch,170,server)
            if server.poll() is not None:raise RuntimeError("CARLA server exited during probe")
            available=json.loads((root/"probe.json").read_text())["available_maps"]
            if any(not any(path.split("/")[-1]==wanted for path in available) for wanted in plan["maps"]):
                raise ValueError("A requested standard town is not advertised by server")
            # Actual CARLA quality is verified from logs, not solely a declared collector flag.
            proof=quality_proof(name,log_path)
            save(root/"quality_proof.json",proof)
            watch.set_phase(name+":six_camera_capture")
            command=[str(PYTHON),"-B",str(RUN/"code/rig_capture.py"),"capture","--map",name,"--port",str(PORT)]
            save(root/"capture_command.json",dict(argv=command,cwd=str(RUN)))
            capture_log=(RUN/"logs"/(name+"_capture.log")).open("x");opened.append(capture_log)
            child=subprocess.Popen(command,cwd=str(RUN),env=env,stdout=capture_log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((child,name+":collector"));watch.track(child,name+":collector")
            wait_child(child,name+":capture",watch,150,server)
            watch.set_phase(name+":server_teardown")
            stop_owned(server,name+":server",watch.events)
            wait_released(watch,baseline)
            watch.set_phase(name+":CPU_validation")
            command=[str(PYTHON),"-B",str(RUN/"code/validate_capture.py"),"--map",name]
            validate_log=(RUN/"logs"/(name+"_validation.log")).open("x");opened.append(validate_log)
            child=subprocess.Popen(command,cwd=str(RUN),env=env,stdout=validate_log,stderr=subprocess.STDOUT,start_new_session=True)
            processes.append((child,name+":validation"));watch.track(child,name+":validation")
            wait_child(child,name+":validation",watch,60)
            summary["maps"][name]=dict(status="passed",images=6,scene_path=str(RUN/"results/scenes"/name),
                validation=str(RUN/"reports"/(name+"_validation.json")),quality=proof,
                sampled_peak_used_mib=max(s["used_mib"] for s in watch.samples[start_sample:]))
            print(name+" COMPLETE: 6 images, exact rig, server stopped, sampled peak %.1f MiB"%summary["maps"][name]["sampled_peak_used_mib"],flush=True)
        summary["status"]="completed_all_requested_maps"
    except BaseException as error:
        summary.update(status="stopped_on_threshold_or_error",error=repr(error),traceback=traceback.format_exc())
        if current and summary["maps"][current]["status"]=="not_started":
            summary["maps"][current]=dict(status="failed",error=repr(error))
        print("Stopped: "+repr(error),flush=True)
    finally:
        watch.set_phase("final_cleanup")
        for proc,label in reversed(processes):stop_owned(proc,label,watch.events)
        try:
            if watch.samples and not watch.error:wait_released(watch,watch.samples[0]["used_bytes"])
        except Exception as error:summary["cleanup_memory_error"]=repr(error)
        summary["gpu_monitor"]=watch.close()
        for f in opened:f.close()
        try:assert_frozen();summary["protected_original_sources_unchanged"]=True
        except Exception as error:summary["protected_original_sources_unchanged"]=False;summary["protection_error"]=repr(error)
        summary.update(elapsed_s=time.monotonic()-started,all_owned_children_exited=all(p.poll() is not None for p,_ in processes),
                       unrelated_processes_signaled=False,remaining_maps=[n for n,r in summary["maps"].items() if r["status"]!="passed"])
        save(RUN/"summary.json",summary);report(summary)
    if summary["status"]!="completed_all_requested_maps":raise SystemExit(2)

if __name__=="__main__":main()
