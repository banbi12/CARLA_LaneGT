"""Read-only NVML sampling; signal only process groups created by this supervisor."""
import ctypes
import csv
import json
import os
from pathlib import Path
import signal
import threading
import time

MIB = 1024**2

class MemoryInfo(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]

class NVML:
    def __init__(self, index=0):
        self.lib = ctypes.CDLL("libnvidia-ml.so.1")
        self.lib.nvmlInit_v2.restype = ctypes.c_int
        self.lib.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        self.lib.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryInfo)]
        self.handle = ctypes.c_void_p()
        self.check(self.lib.nvmlInit_v2())
        self.check(self.lib.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(self.handle)))
    @staticmethod
    def check(result):
        if result != 0:
            raise RuntimeError("NVML call failed with code "+str(result))
    def sample(self):
        m = MemoryInfo()
        self.check(self.lib.nvmlDeviceGetMemoryInfo(self.handle, ctypes.byref(m)))
        return dict(wall_time_s=time.time(), total_bytes=int(m.total), free_bytes=int(m.free), used_bytes=int(m.used),
                    used_mib=float(m.used)/MIB)
    def close(self):
        self.check(self.lib.nvmlShutdown())

def signal_owned(proc, sig):
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.getpgid(proc.pid) != proc.pid:
            raise RuntimeError("Owned process has unexpected process group")
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass

def stop_owned(proc, label, events):
    if proc is None:
        return
    if proc.poll() is None:
        events.append(dict(action="terminate_owned_process_group", label=label, pid=proc.pid, wall_time_s=time.time()))
        signal_owned(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except __import__("subprocess").TimeoutExpired:
            events.append(dict(action="kill_owned_unresponsive_process_group", label=label, pid=proc.pid, wall_time_s=time.time()))
            signal_owned(proc, signal.SIGKILL)
            proc.wait(timeout=5)
    else:
        proc.wait(timeout=1)

class MemoryWatch:
    def __init__(self, root, limit_bytes, interval=.1):
        self.root = Path(root); self.limit_bytes = limit_bytes; self.interval = interval
        self.reader = NVML(); self.samples = []; self.phase = "preflight"; self.error = None
        self.trigger = None; self.stop_event = threading.Event(); self.lock = threading.Lock()
        self.processes = []; self.events = []; self.thread = None
        self.stream = (self.root/"runtime/gpu_memory.csv").open("x", newline="", buffering=1)
        self.writer = csv.DictWriter(self.stream, fieldnames=["wall_time_s","phase","used_bytes","used_mib","free_bytes","total_bytes"])
        self.writer.writeheader()
    def track(self, proc, label):
        with self.lock:
            self.processes.append((proc,label))
        self.check()
    def set_phase(self, phase):
        self.phase = phase
        self.events.append(dict(action="phase", phase=phase, wall_time_s=time.time()))
    def sample(self):
        sample = self.reader.sample(); sample["phase"] = self.phase
        self.samples.append(sample); self.writer.writerow(sample)
        if sample["used_bytes"] >= self.limit_bytes:
            raise RuntimeError("GPU memory reached effective stop threshold: %.2f MiB >= %.2f MiB" %
                               (sample["used_mib"], self.limit_bytes/MIB))
        return sample
    def abort(self, error):
        self.error = str(error); self.trigger = dict(error=str(error), phase=self.phase, wall_time_s=time.time(),
                                                   sample=self.samples[-1] if self.samples else None)
        with self.lock:
            processes = list(self.processes)
        self.events.append(dict(action="threshold_or_monitor_abort", **self.trigger))
        for proc,label in processes:
            if proc.poll() is None:
                self.events.append(dict(action="immediate_SIGTERM_owned_group", label=label, pid=proc.pid))
                signal_owned(proc, signal.SIGTERM)
    def start(self):
        self.sample()
        def loop():
            while not self.stop_event.wait(self.interval):
                try:
                    self.sample()
                except Exception as error:
                    self.abort(error); return
        self.thread = threading.Thread(target=loop, daemon=True); self.thread.start()
    def check(self):
        if self.error:
            raise RuntimeError(self.error)
    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
        self.stream.close(); self.reader.close()
        summary = dict(effective_limit_bytes=self.limit_bytes, effective_limit_mib=self.limit_bytes/MIB,
                       requested_sample_interval_s=self.interval, sample_count=len(self.samples),
                       sampled_peak_used_mib=max((s["used_mib"] for s in self.samples), default=None),
                       sampled_peak_used_bytes=max((s["used_bytes"] for s in self.samples), default=None),
                       threshold_or_monitor_trigger=self.trigger,
                       limitation="A sampling-triggered stop is not a GPU hardware allocation cap; unobserved sub-interval peaks remain possible",
                       events=self.events)
        with (self.root/"runtime/gpu_monitor_summary.json").open("x") as f:
            json.dump(summary,f,indent=2)
        return summary
