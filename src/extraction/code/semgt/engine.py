"""Observation-led dividers, guarded generated bridges and four-class assembly."""
import copy
import numpy as np
from shapely.geometry import LineString,box
from . import VERSION
from .geometry import transform,parts,validate_meta,uid
from .observations import extract
from .topology import double_yellow,connect_dashes
from .divider_base import merge_divider_base
from .policy import checked
from .hints import annotate

def dividers(meta,labels,depth,rgb,policy=None,old_world=None,connection_reference=None,divider_base=None):
    """All decisions precede optional hints; output geometry has no hint-derived fields."""
    policy=checked(policy);atoms,stripes,stats=extract(meta,labels,depth,rgb,policy)
    base_mode=policy.get('divider_base_mode')=='xodr_v41'
    if base_mode:
        # The V4.1 base owns continuity; semantic supplements use short gaps only.
        policy=dict(policy,dash_max_gap_m=2.,dash_straight_max_gap_m=2.)
    paired,double_audit=double_yellow(atoms,meta,policy,labels,depth)
    connected,joins,rejected=connect_dashes(paired,meta,labels,depth,stripes,policy,connection_reference)
    # The adopted no-angle short-gap function is vendored separately; stop mask is empty.
    from small_gaps import fill_small_gaps
    final,gaps,gap_rejected=fill_small_gaps(connected,meta,labels,depth,stripes,np.zeros(labels.shape,bool))
    for f in final:f['id']=uid(f['points_xyz'],f['class_name'])
    base_audit=None
    if base_mode and divider_base:
        final,base_audit=merge_divider_base(divider_base,final,policy)
    audit=dict(observation_stats=stats,double_yellow=double_audit,dash_connections=joins,
               small_gap_connections=gaps,rejected_connections=rejected+gap_rejected,
               stopline_hard_deletion=False,stopline_barrier_enabled=False,
               observed_crosswalk_mask=stripes,raw_observations=atoms,
               divider_base=base_audit,
               connection_reference=connection_reference.describe() if connection_reference is not None else dict(status='not_supplied',scope='no_map_based_observation_filter'))
    hints=annotate(final,old_world)
    return final,audit,hints

def repair_boundaries(features,meta,labels,depth,stripes,policy):
    """Run the adopted 0.35m rule, then a boundary-only smooth short-gap pass."""
    from small_gaps import fill_small_gaps
    result,gaps,rejected=fill_small_gaps(features,meta,labels,depth,stripes,np.zeros(labels.shape,bool),allowed_classes=('boundary',))
    smooth_gaps=[]
    if policy.get('boundary_smooth_enabled'):
        result,smooth_gaps,smooth_rejected=fill_small_gaps(
            result,meta,labels,depth,stripes,np.zeros(labels.shape,bool),
            allowed_classes=('boundary',),max_gap_m=policy['boundary_smooth_max_gap_m'],
            min_tangent_chord_dot=policy['boundary_smooth_min_tangent_dot'],
            max_curve_chord_ratio=policy['boundary_smooth_max_curve_ratio'])
        for record in smooth_gaps:record['boundary_smooth_connection']=True
        gaps+=smooth_gaps;rejected+=smooth_rejected
    for feature in result:
        if feature['class_name']=='boundary' and feature.get('gap_repaired'):
            feature['id']=uid(feature['points_xyz'],'boundary')
            smooth=any(record.get('boundary_smooth_connection') for record in feature.get('connections',[]))
            feature['source']=dict(kind='observed_semantic_boundary_with_smooth_gap_repair' if smooth else 'observed_semantic_boundary_with_short_gap_repair',
                original_source=feature['source'],source_ids=[g['source_ids'] for g in feature['connections']],
                gap_limit_m=.35,smooth_gap_limit_m=policy['boundary_smooth_max_gap_m'],
                angle_rejection_enabled=False,smooth_angle_rejection_enabled=smooth)
    return result,gaps,rejected

def clip_targets(features,model_from_world,partition_policy,bev_range=None):
    from partition import make_partition,check_partition
    matrix=np.asarray(model_from_world,float)
    if matrix.shape!=(4,4) or not np.isfinite(matrix).all() or not np.allclose(matrix[3],[0,0,0,1]):
        raise ValueError('Full measured model-from-world transform is required')
    if not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-5):
        raise ValueError('The measured model transform must be rigid')
    from .bev import bounds
    roi=box(*bounds(bev_range));targets=[]
    for f in features:
        cls=f['class_name']
        if cls not in ['divider','boundary','ped_crossing']:continue
        if cls=='boundary':
            parent=dict(id=f['id'],points_xyz=f['points_xyz']);children=make_partition(parent,partition_policy);check_partition(parent,children,partition_policy)
        else:children=[f]
        for child in children:
            local=transform(child['points_xyz'],matrix)
            for index,line in enumerate(parts(LineString(local).intersection(roi))):
                if line.length<=.05:continue
                p=np.asarray(line.coords);targets.append(dict(id=child['id']+':clip'+str(index),parent_id=f['id'],class_name=cls,full=p[:,:2].tolist(),full_xyz=p.tolist(),source=f['source']))
    return targets

def assemble(row,features,centerline,partition_policy,sampled=None,bev_range=None):
    """Copy centerline verbatim. Full geometry is the base annotation; model sampling is optional."""
    from .bev import bounds
    bev_range=bounds(bev_range if bev_range is not None else row.get('BEV_range_m'))
    targets=clip_targets(features,row['transform'],partition_policy,bev_range)
    for f in centerline:
        targets.append(dict(id=f['id'],parent_id=f['parent_id'],class_name='centerline',full=copy.deepcopy(f['render_points']),full_xyz=copy.deepcopy(f['render_xyz']),source=copy.deepcopy(f['source'])))
    if len({f['id'] for f in targets})!=len(targets):raise ValueError('Duplicate target IDs')
    classes={k:[] for k in ['divider','ped_crossing','boundary','centerline']}
    for index,f in enumerate(targets):
        if f['class_name']=='centerline':continue
        points=sampled['fixed20'][index].tolist() if sampled is not None else None
        classes[f['class_name']].append(dict(id=f['id'],parent_id=f['parent_id'],source=f['source'],render_points=f['full'],render_xyz=f['full_xyz'],points=points,human_approved=False))
    classes['centerline']=copy.deepcopy(centerline)
    gt=dict(schema='maptrv2_semantic_gt_v1',algorithm_version=VERSION,token=row['token'],reference=row['reference'],classes=classes,counts={k:len(v) for k,v in classes.items()},
            geometry_frame='map_model_local_x_right_y_forward_z_up',BEV_range_m=bev_range,centerline_exact_from_source=True,algorithm_accepted_by_user=False,human_approved=False,
            actual_sampler_applied=sampled is not None,capacity_passed=len(targets)<=128,approved_for_training=False)
    from .portable import finalize
    return finalize(gt,sampled is not None),targets
