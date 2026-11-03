"""MapTRv2 dataset adapter for converted CARLA-OpenLane Subset B indices."""
from pathlib import Path

import numpy as np
from mmdet.datasets import DATASETS
from pyquaternion import Quaternion

from projects.mmdet3d_plugin.datasets.nuscenes_offlinemap_dataset import (
    CustomNuScenesOfflineLocalMapDataset,
)


@DATASETS.register_module()
class CarlaOpenLaneMapDataset(CustomNuScenesOfflineLocalMapDataset):
    """Uses an explicit local map frame; no point cloud or depth labels."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # MapTR's sampler clamps about zero; annotations remain clipped to the
        # requested ROI while this envelope supports asymmetric coordinates.
        a,b,_,c,d,_=self.pc_range
        if abs(a+c)>1e-7 or abs(b+d)>1e-7:
            if self.aux_seg.get('use_aux_seg'):raise ValueError('非对称BEV的aux_seg尚未支持')
            self.vector_map.patch_size=(2*max(abs(b),abs(d)),2*max(abs(a),abs(c)))
        # nuscenes-devkit stores DetectionConfig.class_names as dict_keys,
        # which DataLoader workers cannot pickle. The map task never uses the
        # detection config, but it is still part of the dataset object.
        cfg = getattr(self, 'eval_detection_configs', None)
        if cfg is not None:
            cfg.class_names = list(cfg.class_names)

    def get_data_info(self, index):
        info = self.data_infos[index]
        ego2global = np.asarray(info['ego2global'], dtype=np.float64)
        lidar2global = np.asarray(info['lidar2global'], dtype=np.float64)
        lidar2ego = np.asarray(info['lidar2ego'], dtype=np.float64)
        q = Quaternion(matrix=ego2global[:3, :3])
        yaw = np.arctan2(lidar2global[1, 0], lidar2global[0, 0])
        can_bus = np.zeros(18, dtype=np.float64)
        can_bus[:3] = lidar2global[:3, 3]
        can_bus[3:7] = q.elements
        can_bus[-2] = yaw
        can_bus[-1] = np.rad2deg(yaw)
        root = Path(self.data_root)
        images, lidar2img, lidar2cam, cam_intrinsic = [], [], [], []
        camera2ego, camera_intrinsics, camego2global = [], [], []
        cam2lidar = []
        for name in ('CAM_FRONT', 'CAM_FRONT_LEFT', 'CAM_FRONT_RIGHT',
                     'CAM_BACK', 'CAM_BACK_LEFT', 'CAM_BACK_RIGHT'):
            cam = info['cams'][name]
            images.append(str(root / cam['image_path']))
            c2e = np.asarray(cam['cam2ego'], dtype=np.float32)
            c2l = np.linalg.inv(lidar2ego).astype(np.float32) @ c2e
            l2c = np.linalg.inv(c2l)
            k = np.eye(4, dtype=np.float32)
            k[:3, :3] = cam['intrinsic']
            camera2ego.append(c2e)
            camera_intrinsics.append(k)
            camego2global.append(ego2global.astype(np.float32))
            cam2lidar.append(c2l)
            lidar2cam.append(l2c)
            lidar2img.append(k @ l2c)
            cam_intrinsic.append(k)
        return dict(sample_idx=info['token'], scene_token=info['scene_token'],
                    frame_idx=info['frame_idx'], timestamp=info['timestamp'],
                    prev_idx='', next_idx='', can_bus=can_bus,
                    ego2global_translation=ego2global[:3, 3],
                    ego2global_rotation=q.elements,
                    lidar2ego=lidar2ego.astype(np.float32),
                    lidar2global=lidar2global.astype(np.float32),
                    img_filename=images, lidar2img=lidar2img,
                    lidar2cam=lidar2cam, cam2lidar=cam2lidar,
                    cam_intrinsic=cam_intrinsic, camera2ego=camera2ego,
                    camera_intrinsics=camera_intrinsics,
                    camego2global=camego2global,
                    ann_info=info['annotation'], annotation=info['annotation'])
