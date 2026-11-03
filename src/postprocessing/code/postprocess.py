"""Apply exported geometry edits with optional model sampling on CPU, into a new dataset."""
from pathlib import Path
import argparse, copy, importlib.util, json, os, shutil, sys
from project import load, save, sha, index, link, build_web, PACKAGE, BASE, DEFAULT_SOURCE
from edit_model import replay, targets_from_gt, edited_gt


def validated_patch(source, doc):
    ds = index(source); rows = {r['token']: r for r in load(source/'manifest/frames.json')}
    hashes = {f['token']: f['gt_sha256'] for f in ds['frames_index']}
    if doc.get('schema') != 'maptrv2_gt_edit_patch_v1' or doc.get('dataset_id') != ds['dataset_id'] or doc.get('manifest_sha256') != ds['manifest_sha256']:
        raise ValueError('Patch schema/dataset/manifest mismatch')
    frames = doc.get('frames')
    if not isinstance(frames, dict): raise ValueError('frames must be an object')
    checked = {}
    for token, patch in frames.items():
        if token not in rows or not isinstance(patch, dict): raise ValueError('Unknown frame '+str(token))
        folder = source/'frames'/token; digest = sha(folder/'gt.json.gz')
        if digest != hashes.get(token): raise ValueError('Dataset index is stale '+token)
        if patch.get('base_gt_sha256') != digest: raise ValueError('Base GT hash mismatch '+token)
        operations = patch.get('operations'); original = load(folder/'targets.json.gz')
        gt = load(folder/'gt.json.gz'); base = targets_from_gt(gt, [f['id'] for f in original])
        targets = replay(base, operations,gt.get('BEV_range_m'))
        if operations: checked[token] = dict(gt=gt, targets=targets, operations=operations, sha=digest)
    if not checked: raise ValueError('No active edits in patch')
    return checked


def materialize(source, patch_path, output, sampler='none'):
    os.environ.update(CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    source = source.resolve(); output = output.absolute()
    from workspace import settings
    cfg = settings(PACKAGE,source)
    canonical = Path(cfg['canonical_review']); patch = load(patch_path)
    checked = validated_patch(source, patch)  # Validate every operation before creating output.
    if output.exists() or output.is_symlink(): raise FileExistsError('Output must be new: '+str(output))
    protected = [source, canonical, PACKAGE, BASE/'ARCHIVE_20261031',
                 (source/'native_images').resolve(), (source/'topdown_cases').resolve()]
    # Existing datasets and the native inputs must never be an output ancestor.
    if BASE.exists(): protected += [p.resolve() for p in BASE.iterdir() if p.is_dir()]
    protected += [Path(cfg['repository_root'])/p for p in ['src','config','assets','archive','provenance','web']]
    for root in protected:
        if output.resolve() == root or root in output.resolve().parents: raise ValueError('Output lies inside protected source: '+str(root))
    all_source = {str((source/'frames'/r['token']/name).resolve()): sha(source/'frames'/r['token']/name)
        for r in load(source/'manifest/frames.json') for name in ['gt.json.gz', 'targets.json.gz', 'actual_sampler_targets.npz'] if (source/'frames'/r['token']/name).is_file()}
    # Import the delivered renderer with an explicit new output root. It writes only copied geometry.
    sys.path.insert(0, cfg['extractor_code'])
    spec = importlib.util.spec_from_file_location('manual_base_renderer', Path(cfg['review_code'])/'render_review.py')
    renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
    from semgt.sampling import actual_targets, diagnostics
    import numpy as np
    output.mkdir(parents=True); (output/'frames').mkdir(); (output/'geometry').mkdir()
    for name in ['topdown_cases', 'native_images']: link(output/name, source/name)
    (output/'config').mkdir(); shutil.copy2(cfg['paths_file'], output/'config/paths.json')
    rows = load(source/'manifest/frames.json'); changed_refs = {r['reference'] for r in rows if r['token'] in checked}
    refs = {r['reference'] for r in rows}
    for ref in refs:
        if ref in changed_refs: shutil.copytree(source/'geometry'/ref, output/'geometry'/ref)
        else: link(output/'geometry'/ref, source/'geometry'/ref)
    renderer.R = output; reports = []
    for row in rows:
        token = row['token']; frame = output/'frames'/token
        if token not in checked:
            link(frame, source/'frames'/token); continue
        data = checked[token]; targets = data['targets']; sampled = actual_targets(targets, cfg['model_root'],data['gt'].get('BEV_range_m')) if sampler=='maptr' else None
        sampling_report = diagnostics(targets, sampled) if sampled is not None else dict(status='not_requested')
        gt = edited_gt(data['gt'], targets, data['operations'], data['sha'], sampled)
        assert [(f['id'],f['render_xyz']) for f in gt['classes']['centerline']] == [(f['id'],f['render_xyz']) for f in data['gt']['classes']['centerline']]
        frame.mkdir(); save(frame/'gt.json.gz', gt); save(frame/'targets.json.gz', targets)
        save(frame/'sampling_diagnostics.json', sampling_report)
        if sampled is not None:np.savez_compressed(frame/'actual_sampler_targets.npz', target_ids=np.asarray([t['id'] for t in targets]), **sampled)
        shutil.copy2(source/'frames'/token/'input_binding.json', frame/'input_binding.json')
        renderer.render(row)
        reports.append(dict(token=token, operations=len(data['operations']), counts=gt['counts'], new_gt_sha256=sha(frame/'gt.json.gz'),
            actual_sampler_applied=sampled is not None, centerline_exact=True, capacity_passed=gt['capacity_passed']))
    ds = copy.deepcopy(index(source)); ds.update(dataset_id=output.name+'_MANUAL_V1', version=ds['version']+'+manual_v1')
    for f in ds['frames_index']:
        if f['token'] in checked:
            c = load(output/'frames'/f['token']/'COMPLETE.json')
            f.update(actual_sampler_applied=c['actual_sampler_applied'],counts=c['counts'], instances=c['instances'], gt_sha256=c['gt_sha256'], capacity_passed=c['capacity_passed'], sampling_warning_count=len(c['sampling_over_020m']))
    build_web(output, source, dataset=ds)
    for name, digest in all_source.items():
        if sha(name) != digest: raise AssertionError('Source modified: '+name)
    save(output/'edits/APPLIED_PATCH.json', patch)
    save(output/'reports/MANUAL_APPLY.json', dict(passed=True, source=str(source), changed_frames=reports,
        unchanged_frames_linked=len(rows)-len(checked), source_hashes_verified=len(all_source),
        geometry_directory='Original observation evidence; manual actual GT lives in frames/*/gt.json.gz and targets.json.gz',
        GPU_used=False, CARLA_started=False, approved_for_training=False))
    save(output/'DELIVERY_FILES_SHA256.json', dict(files={str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file() and not p.is_symlink()},
        directory_symlinks={str(p.relative_to(output)): os.readlink(p) for p in output.rglob('*') if p.is_symlink()}, approved_for_training=False))
    print(json.dumps(dict(passed=True, output=str(output), changed_frames=len(checked), GPU_used=False), ensure_ascii=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--patch', type=Path, required=True)
    ap.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--sampler',choices=['none','maptr'],default='none')
    args = ap.parse_args(); materialize(args.source, args.patch, args.output,args.sampler)
