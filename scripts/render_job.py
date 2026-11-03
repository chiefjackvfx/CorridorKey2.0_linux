#!/usr/bin/env python3
"""Desktop render transaction: infer in private storage, validate, publish pass folders."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['OPENCV_IO_ENABLE_OPENEXR']='1'
from linux_export import Reservation,runtime_passes,validate_passes,publish_passes,write_json,source_frames
from linux_jobs import Options,build_command


def execute_job(job_path):
    job_path=Path(job_path);job=json.loads(job_path.read_text());work=job_path.parent
    options=Options(**job['options']);reservation=None;child=None
    def update(status,**values):
        candidate={**job,'status':status,**values}
        write_json(job_path,candidate)
        job.clear();job.update(candidate)
    def cancel(signum,frame):raise InterruptedError('Render cancelled before completion.')
    previous=signal.signal(signal.SIGTERM,cancel)
    try:
        reservation=Reservation.reserve(job['source'],job['base'],options.outputs,sibling=options.save_sibling,
                                        output_format=options.output_format,owner=job['id'])
        plan=reservation.plan
        update('running',plan=vars(plan),reservation=str(reservation.lock),passes={})
        print('Export targets:',*plan.preview,sep='\n  ',flush=True)
        expected=len(source_frames(job['source'])) if Path(job['source']).is_dir() else None
        if expected is None:
            import cv2
            cap=cv2.VideoCapture(job['source'])
            try:expected=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
            finally:cap.release()
        if options.num_frames>0:expected=min(expected,options.num_frames) if expected else options.num_frames
        directory=work/'render'
        command=build_command(ROOT,sys.executable,job['source'],directory,options)
        child=subprocess.Popen(command)
        code=child.wait()
        if code:raise RuntimeError(f'Inference failed with exit code {code}. See inference.log.')
        update('validating')
        files=runtime_passes(directory,options.outputs,options.output_format)
        count,hw=validate_passes(files,options.output_format,expected)
        settings=list(directory.glob('*_settings.txt'))
        if len(settings)!=1:raise ValueError('The render settings receipt is missing or ambiguous.')
        update('publishing',frame_count=count,dimensions=list(hw))
        def committed(passes):
            update('complete',passes=passes,first_frame=plan.first_frame,
                   settings=str(settings[0]))
        published=publish_passes(reservation,files,committed)
        # Keep settings/logs; remove only this attempt's finished staging media.
        for key,paths in files.items():
            if options.output_format=='exr':
                import shutil
                shutil.rmtree(paths[0].parent,ignore_errors=True)
            else:paths[0].unlink(missing_ok=True)
        print('Published completed passes:',*published.values(),sep='\n  ',flush=True)
        return 0
    except BaseException as exc:
        if job.get('status')=='complete':
            print('[Export complete; cleanup warning]',str(exc),flush=True)
            return 0
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:child.kill();child.wait()
        update('cancelled' if isinstance(exc,(InterruptedError,KeyboardInterrupt)) else 'failed',error=str(exc))
        print('[Export failed]',str(exc),flush=True)
        return 1
    finally:
        if reservation is not None:reservation.close()
        signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':raise SystemExit(execute_job(sys.argv[1]))
