"""Export a candidate index; exercise the real Dataset, vector pipeline and CPU DataLoader."""
from pathlib import Path
import sys,os,json,pickle,functools,collections
os.environ.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
REPO=Path(__file__).resolve().parents[3];sys.path.insert(0,str(REPO/'src/extraction/code'))
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'code'))
from semgt.io import load,save,sha
import numpy as np

def main():
    global R
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);R=ap.parse_args().root
    if (R/'reports/DELIVERY_FILES_SHA256.json').exists() or (R/'PROJECT_FILES_SHA256.json').exists():raise ValueError('Create a new review workspace before writing Dataset diagnostics')
    paths=load(R/'config/paths.json')
    if not paths.get('model_root'):raise ValueError('dataset-check 是可选 MapTRv2 检查；通用 GT 请使用 geometry-check，或先配置适配器并 export-maptr')
    rows=load(R/'manifest/frames.json');classes=['divider','ped_crossing','boundary','centerline']
    from semgt.bev import bounds
    bev_range=bounds(load(R/'frames'/rows[0]['token']/'gt.json.gz').get('BEV_range_m'))
    if not all(r.get('image_paths') for r in rows):
        from semgt.sampling import actual_targets
        for row in rows:
            frame=R/'frames'/row['token'];targets=load(frame/'targets.json.gz');actual=actual_targets(targets,paths['model_root'],bev_range)
            with np.load(frame/'actual_sampler_targets.npz') as saved:
                assert saved['target_ids'].tolist()==[t['id'] for t in targets]
                for key in ['fixed20','shift_v2','labels']:assert np.array_equal(actual[key],saved[key])
        report=dict(passed=True,mode='topdown_vectors_only',frames=len(rows),BEV_range_m=bev_range,real_sampler_checked=True,real_camera_Dataset_checked=False,DataLoader_real_image_samples=0,GPU_used=False)
        save(R/'reports/DATASET_INTERFACE_CHECKS.json',report);print(json.dumps(report));return
    native_from_map=np.array([[0,1,0,0],[-1,0,0,0],[0,0,1,0],[0,0,0,1]])
    infos=[]
    for row in rows:
        meta=load(Path(paths['native_metadata'])/(row['token']+'.json.gz'));gt=load(R/'frames'/row['token']/'gt.json.gz');ego=np.asarray(meta['native_to_world_flu'])
        assert np.allclose(ego@native_from_map,np.diag([1,-1,1,1])@np.linalg.inv(row['transform']),atol=2e-6)
        info=dict(token=row['token'],scene_token=meta['scene_token'],frame_idx=row['frame_idx'],timestamp=meta['timestamp_us'],
            cams={name:dict(image_path=c['image_path'],cam2ego=c['optical_to_native'],intrinsic=c['intrinsic']) for name,c in meta['cameras'].items()},
            ego2global=ego.tolist(),lidar2ego=native_from_map.tolist(),lidar2global=(ego@native_from_map).tolist(),
            annotation={c:[f['render_points'] for f in gt['classes'][c]] for c in classes},
            annotation_target_ids={c:[f['id'] for f in gt['classes'][c]] for c in classes},
            status='candidate_not_approved_for_training',sample_split=row['sample_split'],gt_sha256=sha(R/'frames'/row['token']/'gt.json.gz'))
        infos.append(info)
    index=R/'dataset/index/review60.pkl';index.parent.mkdir(parents=True,exist_ok=True)
    with index.open('wb') as stream:pickle.dump(dict(infos=infos,metadata=dict(version='v1.0-test',classes=classes,annotation_sampling='full_geometry; real Dataset samples fixed20/shift_v2',approved_for_training=False)),stream,protocol=4)
    model=Path(paths['model_root']);sys.path[:0]=[str(model),str(model/'mmdetection3d'),str(REPO/'src/adapters')]
    import torch
    torch.set_num_threads(1)
    from carla_map_dataset import CarlaOpenLaneMapDataset
    from torch.utils.data import DataLoader,Subset
    from mmcv.parallel import collate
    pipeline=[dict(type='LoadMultiViewImageFromFiles',to_float32=True),dict(type='DefaultFormatBundle3D',class_names=[],with_gt=False),dict(type='CustomCollect3D',keys=['img'])]
    dataset=CarlaOpenLaneMapDataset(data_root='/',ann_file=str(index),pipeline=pipeline,test_mode=False,filter_empty_gt=False,queue_length=1,
        map_classes=classes,fixed_ptsnum_per_line=20,pc_range=[bev_range[0],bev_range[1],-5,bev_range[2],bev_range[3],3],bev_size=(200,100),modality=dict(use_camera=True,use_lidar=False,use_radar=False,use_map=False,use_external=False),aux_seg=dict(use_aux_seg=False,bev_seg=False,pv_seg=False,seg_classes=1,feat_down_sample=32))
    verified=[];maximum_projection_delta=0.
    for i,info in enumerate(dataset.data_infos):
        row=next(r for r in rows if r['token']==info['token']);data=dataset.get_data_info(i)
        example=dataset.vectormap_pipeline({},data);lines=example['gt_bboxes_3d'].data;fixed=lines.fixed_num_sampled_points.numpy()
        state=np.random.get_state()
        try:np.random.seed(0);shift=lines.shift_fixed_num_sampled_points_v2.numpy()
        finally:np.random.set_state(state)
        ordered_ids=[identifier for c in classes for identifier in info['annotation_target_ids'][c]]
        expected=np.load(R/'frames'/info['token']/'actual_sampler_targets.npz');lookup={identifier:j for j,identifier in enumerate(expected['target_ids'].tolist())};order=[lookup[k] for k in ordered_ids]
        assert np.array_equal(fixed,expected['fixed20'][order]) and np.array_equal(shift,expected['shift_v2'][order])
        assert np.array_equal(example['gt_labels_3d'].data.numpy(),expected['labels'][order])
        meta=load(Path(paths['native_metadata'])/(info['token']+'.json.gz'))
        camera_order=('CAM_FRONT','CAM_FRONT_LEFT','CAM_FRONT_RIGHT','CAM_BACK','CAM_BACK_LEFT','CAM_BACK_RIGHT')
        for j,name in enumerate(camera_order):
            k=np.eye(4);k[:3,:3]=meta['cameras'][name]['intrinsic'];manual=k@np.linalg.inv(meta['cameras'][name]['optical_to_native'])@native_from_map
            delta=float(np.abs(data['lidar2img'][j]-manual).max());maximum_projection_delta=max(maximum_projection_delta,delta)
            assert delta<.001 and data['img_filename'][j]==row['image_paths'][name]
        verified.append(info['token'])
    sample_indices=sorted(set([0,len(dataset)//2,len(dataset)-1]))
    batches=[]
    loader=DataLoader(Subset(dataset,sample_indices),batch_size=2,num_workers=0,pin_memory=False,collate_fn=functools.partial(collate,samples_per_gpu=2))
    for batch in loader:
        tensor=batch['img'].data[0];assert tensor.ndim==6 and tuple(tensor.shape[1:])==(1,6,3,900,1600) and torch.isfinite(tensor).all()
        batches.append(list(tensor.shape));del batch,tensor
    source_files=[model/'projects/mmdet3d_plugin/datasets/nuscenes_offlinemap_dataset.py',REPO/'src/adapters/carla_map_dataset.py']
    report=dict(passed=True,dataset_class='CarlaOpenLaneMapDataset',real_dataset_entries=len(dataset),real_vector_pipeline_checks=len(verified),
        full_geometry_input=True,fixed20_and_shift_v2_exact_match=True,class_ids_and_target_ids_matched=True,
        six_camera_order_verified=True,maximum_lidar2img_float32_delta=maximum_projection_delta,
        DataLoader_real_image_samples=len(sample_indices),DataLoader_batch_shapes=batches,queue_length=1,temporal_training_validated=False,
        GPU_used=False,torch_cuda_initialized=torch.cuda.is_initialized(),candidate_index=str(index.relative_to(R)),candidate_index_sha256=sha(index),
        approved_for_training=False,source_SHA256={str(p):sha(p) for p in source_files})
    assert not report['torch_cuda_initialized']
    save(R/'reports/DATASET_INTERFACE_CHECKS.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
