"""Semantic/RGB/road-context classification; no map/prior input exists in this API."""
from collections import defaultdict
import cv2
import numpy as np
from shapely.geometry import LineString
from .geometry import validate_meta,xyworld,uid,trace,local_bend,endpoint
from .stripes import observed_stripes

def yellow_fraction(rgb, pixels):
    color = rgb[pixels[:,1],pixels[:,0]].astype(float)
    return float(((color[:,0]>color[:,2]*1.25+10)&(color[:,1]>color[:,2]*1.2+8)&(color[:,0]>50)).mean())

def arrow_like(paths, scale):
    usable = [p for p in paths if LineString(p).length*scale > .25]
    if len(usable) != 3:
        return False
    lengths = np.array([LineString(p).length*scale for p in usable]);order = np.argsort(lengths)
    if lengths[order[-2]] > 3 or lengths[order[0]] < .25 or lengths[order[-2]]/lengths[order[0]] > 2:
        return False
    if lengths[order[-1]] < lengths[order[-2]]*1.5:
        return False
    # Locate the shared branch and measure outward directions of the three arms.
    ends = [p[[0,-1]] for p in usable]
    candidates = [(sum(min(np.linalg.norm(q-v,axis=1)) for q in ends),v) for p in ends for v in p]
    center = min(candidates,key=lambda x:x[0])[1];vectors = []
    for p in usable:
        if np.linalg.norm(p[-1]-center) < np.linalg.norm(p[0]-center):p=p[::-1]
        vectors.append(endpoint(p*scale,True))
    a,b = [vectors[i] for i in order[:2]];tail = vectors[order[-1]];mean = a+b
    return bool(-.87 < a@b < .91 and np.linalg.norm(mean)>1e-8 and mean@tail/np.linalg.norm(mean)<-.65)

def extract(meta, labels, depth, rgb, policy):
    scale = validate_meta(meta)
    if labels.ndim != 2 or depth.shape != labels.shape or rgb.shape != labels.shape+(3,):
        raise ValueError('Synchronized semantic, metric depth and RGB shapes differ')
    ids = meta.get('semantic_ids',{})
    if any(ids.get(k,v)!=v for k,v in [('Roads',1),('Sidewalks',2),('RoadLines',24)]):
        raise ValueError('Unsupported semantic IDs; no palette-color interpretation is permitted')
    h,w = labels.shape;yy,xx = np.indices(labels.shape)
    if list(meta.get('image_size',[w,h]))!=[w,h]:
        raise ValueError('Measured image size differs from the synchronized arrays')
    rays = np.stack([xx,yy,np.ones_like(xx)],-1) @ np.linalg.inv(np.asarray(meta['intrinsic'])).T
    t = np.asarray(meta['optical_to_world_carla']);world = (rays*depth[:,:,None]) @ t[:3,:3].T+t[:3,3]
    ground = np.isfinite(depth)&(world[:,:,2]>policy['ground_min_z'])&(world[:,:,2]<policy['ground_max_z'])
    interior = np.zeros(labels.shape,bool);border=int(policy['border_px'])
    if h <= 2*border or w <= 2*border:
        raise ValueError('Reference too small for the configured safe border')
    interior[border:h-border,border:w-border] = True
    paint = (labels==24)&ground&interior
    widthmap=cv2.distanceTransform(paint.astype(np.uint8),cv2.DIST_L2,5)*2*scale
    _,paint_components,paint_stats,_=cv2.connectedComponentsWithStats(paint.astype(np.uint8),8)
    compact_broad_symbols=set()
    for index in range(1,len(paint_stats)):
        x,y,bw,bh,_=paint_stats[index];cy,cx=np.where(paint_components[y:y+bh,x:x+bw]==index)
        rect=cv2.minAreaRect(np.c_[cx,cy].astype(np.float32));span=(max(rect[1])+1)*scale
        # Preserve the original component context before stripes split its arms.
        # An isolated compact broad head/stem is unlike a uniformly thin dash.
        if span<4. and np.percentile(widthmap[cy+y,cx+x],95)>policy['maximum_thin_width_m']:
            compact_broad_symbols.add(index)
    stripe_mask,stripe_audit = observed_stripes(paint,scale,policy)
    lines = paint&~stripe_mask
    count,cc,stats,_ = cv2.connectedComponentsWithStats(lines.astype(np.uint8),8)
    original_paths,branchmask = trace(lines)
    paths=[];sharp_parts=set();trace_sources={};trace_lengths={}
    for path in original_paths:
        trace_id=uid(xyworld(path,meta),'observed_trace')
        trace_lengths[trace_id]=float(LineString(path).length*scale)
        pixel=np.rint(path).astype(int)
        broad=widthmap[pixel[:,1],pixel[:,0]]>policy['maximum_thin_width_m']
        arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(path,axis=0),axis=1))]*scale
        before=np.stack([np.interp(np.maximum(0,arc-.2),arc,path[:,j]) for j in range(2)],axis=1)
        after=np.stack([np.interp(np.minimum(arc[-1],arc+.2),arc,path[:,j]) for j in range(2)],axis=1)
        a=path-before;b=after-path
        norm=np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)
        angles=np.degrees(np.arccos(np.clip((a*b).sum(axis=1)/np.maximum(norm,1e-12),-1,1)))
        sharp=(norm>1e-8)&(angles>policy['maximum_local_bend_deg'])
        if sharp.any():
            positions=arc[sharp];sharp=np.min(np.abs(arc[:,None]-positions),axis=1)<.12
        kind=broad.astype(int)+sharp.astype(int)*2
        cuts=np.r_[0,np.flatnonzero(np.diff(kind))+1,len(path)]
        for a,b in zip(cuts[:-1],cuts[1:]):
            piece=path[max(0,a-1):min(len(path),b+1)]
            if len(piece)>=2:
                paths.append(piece)
                trace_sources[id(piece)]=trace_id
                if sharp[a:b].any():sharp_parts.add(id(piece))
    _,branchlabels = cv2.connectedComponents(branchmask,8)
    original_by_component=defaultdict(list)
    for p in original_paths:
        pixel=np.rint(p).astype(int);component=int(cc[pixel[len(pixel)//2,1],pixel[len(pixel)//2,0]])
        original_by_component[component].append(p)
    by_component = defaultdict(list)
    for p in paths:
        pix = np.rint(p).astype(int);component=int(cc[pix[len(pix)//2,1],pix[len(pix)//2,0]])
        by_component[component].append(p)
    contexts = {}
    for component,pp in by_component.items():
        context_paths=original_by_component[component]
        x,y,bw,bh,_ = stats[component];subset=cc[y:y+bh,x:x+bw]==component
        cy,cx=np.where(subset);rect=cv2.minAreaRect(np.c_[cx,cy].astype(np.float32));span=(max(rect[1])+1)*scale
        branches=set(branchlabels[y:y+bh,x:x+bw][subset].tolist())-{0}
        lengths=[LineString(p).length*scale for p in context_paths]
        spur_limit=max(.08,min(.35,max(lengths)*.2));incident=defaultdict(set)
        for index,p in enumerate(context_paths):
            if lengths[index]<spur_limit:continue
            for px,py in np.rint(p[[0,-1]]).astype(int):
                cluster=int(branchlabels[py,px])
                if cluster:incident[cluster].add(index)
        meaningful=sum(len(v)>=3 for v in incident.values())
        closed=any(LineString(p).length*scale>=policy['minimum_stroke_length_m'] and np.linalg.norm(p[0]-p[-1])<1.5 for p in context_paths)
        contexts[component]=dict(span_m=span,pixel_junctions=len(branches),meaningful_junctions=meaningful,closed=closed,
            compact_branching=meaningful>0 and span<policy['compact_span_m'],
            grid_like=meaningful>=policy['grid_junctions'],arrow_like=span<policy['compact_span_m'] and arrow_like(context_paths,scale))
    curb=cv2.distanceTransform((labels!=2).astype(np.uint8),cv2.DIST_L2,5)*scale if np.any(labels==2) else np.full(labels.shape,1e6,np.float32)
    roadmask=np.isin(labels,[1,24])
    road=cv2.distanceTransform(roadmask.astype(np.uint8),cv2.DIST_L2,5)*scale if not roadmask.all() else np.full(labels.shape,100.,np.float32)
    gy,gx=np.gradient(cv2.GaussianBlur(road,(0,0),max(1,.15/scale)))
    features=[]
    for component,pp in sorted(by_component.items()):
        context=contexts[component]
        for path in pp:
            rawline=LineString(path);length=float(rawline.length*scale)
            pix=np.rint(path).astype(int);width=float(np.median(widthmap[pix[:,1],pix[:,0]]))
            frac=float((curb[pix[:,1],pix[:,0]]<policy['curb_distance_m']).mean())
            uv=np.asarray(rawline.simplify(.6,preserve_topology=True).coords);xyz=xyworld(uv,meta);line=LineString(xyz[:,:2])
            bend=local_bend(line) if length>=.2 else 180.
            gradients=np.c_[gx[pix[:,1],pix[:,0]],gy[pix[:,1],pix[:,0]]];norm=np.linalg.norm(gradients,axis=1)
            vectors=np.gradient(path,axis=0);vectors/=np.maximum(np.linalg.norm(vectors,axis=1)[:,None],1e-12)
            support=norm>.2;alignment=np.abs(np.sum(vectors*gradients,axis=1))/np.maximum(norm,1e-12)
            endpoints_near_curb=bool(max(curb[pix[[0,-1],1],pix[[0,-1],0]])<policy['curb_distance_m'])
            transverse=bool(length>1 and endpoints_near_curb and support.mean()>.4 and (alignment[support]>.8).mean()>.8)
            color=yellow_fraction(rgb,pix)
            # Preserve how a short stroke was created. A clipped/fork-split
            # solid rail is not evidence of an isolated physical dash.
            border_touched=bool(np.any((pix[:,0]<=border+1)|(pix[:,0]>=w-border-2)|
                                      (pix[:,1]<=border+1)|(pix[:,1]>=h-border-2)))
            trace_length=trace_lengths[trace_sources[id(path)]]
            cut_from_long_trace=trace_length>max(policy['dash_max_observed_run_m'],length+.2)
            provenance=dict(reference_border_touched=border_touched,
                split_from_branching_component=context['meaningful_junctions']>0,
                component_span_m=context['span_m'],component_junctions=context['meaningful_junctions'],
                observed_piece_length_m=length,original_trace_length_m=trace_length,
                cut_from_long_trace=bool(cut_from_long_trace))
            unsafe_short=(context['span_m']>=max(policy['dash_fragment_parent_min_span_m'],length*policy['dash_fragment_parent_length_ratio'])
                          and context['meaningful_junctions']>0 and (border_touched or cut_from_long_trace))
            provenance['unsafe_short_component_fragment']=bool(unsafe_short)
            broad_symbol=bool(set(paint_components[pix[:,1],pix[:,0]].tolist())&compact_broad_symbols)
            if length<policy['minimum_stroke_length_m']:cls,reason='unresolved','short_observed_stroke_pending'
            elif id(path) in sharp_parts:cls,reason='unresolved','localized_abrupt_junction_pending'
            elif broad_symbol:cls,reason='unresolved','compact_broad_head_or_symbol_pending'
            elif context['grid_like'] or context['arrow_like'] or context['compact_branching']:cls,reason='unresolved','observed_branching_symbol_or_grid_pending'
            elif context['closed'] and context['span_m']<policy['compact_span_m']:cls,reason='unresolved','compact_closed_marking_pending'
            elif width>policy['maximum_thin_width_m']:cls,reason='unresolved','thick_stop_bar_or_symbol_pending'
            elif bend>policy['maximum_local_bend_deg']:cls,reason='unresolved','abrupt_marking_corner_pending'
            elif transverse:cls,reason='unresolved','observed_road_spanning_transverse_mark_pending'
            elif frac>=policy['curb_fraction']:cls,reason='auxiliary','curb_adjacent_paint_pending'
            else:cls,reason='divider','observed_thin_continuous_paint'
            feature=dict(id=uid(xyz,'paint'),class_name=cls,points_xyz=xyz.tolist(),uv=uv.tolist(),
                source_trace_ids=[trace_sources[id(path)]],
                source_components=[int(component)],
                source=reason,review='pending',mark_type='solid',mark_color='yellow' if color>=.55 else 'white',
                dash_eligible=length<=policy['dash_max_observed_run_m'],observed_run_lengths_m=[length],
                observed_segments_xyz=[xyz.tolist()],connections=[],component=int(component),
                evidence=dict(length_m=length,median_width_m=width,near_curb_fraction=frac,
                              max_local_bend_deg=bend,yellow_fraction=color,component_context=context,
                              transverse_candidate=transverse,old_map_used_for_acceptance=False),
                stroke_provenance=provenance,endpoint_provenance=[dict(provenance),dict(provenance)])
            features.append(feature)
    untraced=[dict(component=i,pixels=int(stats[i,4]),reason='isolated_pixels_without_a_traceable_edge') for i in range(1,count) if i not in by_component]
    return features,stripe_mask,dict(stripes=stripe_audit,observed_paint_pixels=int(paint.sum()),untraced_components=untraced,
        observed_strokes=len(features),accepted=sum(f['class_name']=='divider' for f in features),
        pending=sum(f['class_name']!='divider' for f in features),world_pixel_scale_m=scale,
        raw_observations_preserved=True,old_centerline_stop_deletion_enabled=False)
