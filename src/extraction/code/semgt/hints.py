"""Optional after-the-fact annotations. Never called by classification or connection."""
from collections import Counter
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString
from .geometry import sample,tangent

def annotate(features, old_world):
    if not old_world:
        return dict(status='not_provided',affects_GT=False,features={})
    try:
        points=[];directions=[];ids=[]
        for feature in old_world.get('features',{}).values():
            if feature.get('class')!='divider':continue
            line=LineString(np.asarray(feature['points_xyz'])[:,:2]);ss,xy=sample(line,.2)
            points.extend(xy);directions.extend(tangent(line,float(s)) for s in ss);ids.extend([feature['id']]*len(ss))
        if not points:
            return dict(status='empty_divider_hints',affects_GT=False,features={})
        tree=cKDTree(points);directions=np.asarray(directions);result={}
        for f in features:
            if f['class_name']!='divider':continue
            line=LineString(np.asarray(f['points_xyz'])[:,:2]);ss,xy=sample(line,.2);distance,index=tree.query(xy)
            vectors=np.asarray([tangent(line,float(s)) for s in ss]);align=np.abs((vectors*directions[index]).sum(axis=1))
            result[f['id']]=dict(old_prior_support=float(((distance<1.25)&(align>.8)).mean()),nearest_old_id=Counter(ids[i] for i in index).most_common(1)[0][0],median_distance_m=float(np.median(distance)))
        return dict(status='diagnostic_only',affects_GT=False,features=result)
    except Exception as error:
        return dict(status='invalid_optional_hints',affects_GT=False,error=str(error),features={})
