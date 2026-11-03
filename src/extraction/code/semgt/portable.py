"""Model-independent annotation metadata; never resample or alter full geometry."""
def finalize(gt,sampled=False):
    gt['actual_sampler_applied']=bool(sampled)
    if sampled:gt['capacity_passed']=sum(len(v) for v in gt['classes'].values())<=128
    gt['sampling_backend']='maptr' if sampled else 'none'
    gt['geometry_schema']='lanegt_geometry_v1'
    gt['class_order']=['divider','ped_crossing','boundary','centerline']
    gt['units']='metres'
    gt['coordinate_convention']='x_right_y_forward_z_up'
    gt['capacity_check_scope']='optional_MapTRv2_adapter_128_queries'
    if not sampled:
        gt['schema']='lanegt_geometry_v1'
        gt['capacity_passed']=True  # Generic polylines have no query-count limit.
        for entries in gt['classes'].values():
            for f in entries:f['points']=None
    return gt
