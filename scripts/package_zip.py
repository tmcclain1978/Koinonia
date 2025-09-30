#!/usr/bin/env python3
import os, zipfile, pathlib
def include(p: pathlib.Path)->bool:
    parts=set(p.parts)
    if any(seg.startswith('.') for seg in parts): return False
    if 'dist' in parts or 'tests' in parts or 'scripts' in parts: return False
    if p.name in {'Makefile','pyproject.toml','requirements-dev.txt'}: return False
    return p.is_dir() or p.name.endswith(('.py','.html','.css','.js','.json','.jinja2','.jinja','.svg','.png','.jpg','.jpeg','.gif')) or p.name=='requirements.txt'
def main():
    root=pathlib.Path('.').resolve(); dist=root/'dist'; dist.mkdir(parents=True, exist_ok=True)
    out=dist/'app.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in root.rglob('*'):
            if p==out: continue
            if include(p) and p.is_file():
                z.write(p, arcname=str(p.relative_to(root)))
    print(f"Built {out}")
if __name__=='__main__': main()
