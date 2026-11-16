"""Dataset contracts: canonical reading order, geometry, review safety and incrementality."""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/dataset'))
import build_ocr_dataset as builder
from ocr_render import pixel_annotation
from ocr_scan import validate_box


def layout(source, page):
    script = "import {exportLayout} from './tools/dataset/export_ocr_layout.mjs'; import fs from 'node:fs'; const x=JSON.parse(fs.readFileSync(0,'utf8')); console.log(JSON.stringify(exportLayout(x.source,x.page)));"
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            input=json.dumps({'source': source, 'page': page}), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class LayoutContracts(unittest.TestCase):
    def test_mixed_order_supplementary_pua_and_ligature(self):
        # Distinct text exposes the renderer's large-first item order bug.
        source = '@1\n\n#甲\n乙𠀤\n丁\n#(十一)\n\ue701\n庚\n'+'\n@blank\n'*7
        out = layout(source, 1)
        self.assertEqual(out['text'], '甲乙𠀤丁十一\ue701庚')
        self.assertEqual(''.join(r['text'] for r in out['regions']), out['text'])
        self.assertEqual(len(out['glyphs']), len(out['text'])-1)
        ligature = next(g for g in out['glyphs'] if g['ligature'])
        self.assertEqual(ligature['text'], '十一')
        self.assertEqual(ligature['text_range'][1]-ligature['text_range'][0], 2)
        self.assertEqual(len(out['decorations']), 1)

    def test_blank_run_is_gap_not_detection_target(self):
        source = '@1\n\n甲\n*\n'+'\n@blank\n'*7
        out = layout(source, 1)
        self.assertEqual(out['text'], '甲')
        self.assertEqual(len(out['gaps']), 1)
        self.assertEqual(len(out['regions']), 1)
        self.assertEqual(sum(b['empty'] for b in out['bands']), 7)

    def test_scaled_coordinates_and_bounds(self):
        out = layout('@1\n\n#甲\n乙\n丙\n'+'\n@blank\n'*7, 1)
        ann = pixel_annotation(out, 400, 600, 'synthetic', lambda _, b: [b[0]*20+10,b[1]*20+10,b[2]*20+10,b[3]*20+10])
        builder.validate_annotation(ann)
        self.assertEqual(ann['glyphs'][0]['bbox'], [290,10,330,50])
        with self.assertRaises(ValueError): validate_box([0, 0, 450, 20], 400, 600)


class IncrementalContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root/'annotations').mkdir(); (self.root/'images').mkdir(); self.reviews = self.root/'reviews'
        original = builder.read_json(ROOT/'kangxi-gold/manifest.json')
        self.entry = copy.deepcopy(next(e for e in original['pages'] if e['page'] == 312))
        shutil.copyfile(ROOT/'kangxi-gold/annotations/0312.gj', self.root/'annotations/0312.gj')
        Image.new('RGB', (1130,1679), 'white').save(self.root/'images/0312.jpg')
        self.entry['sha256'] = builder.digest(self.root/'images/0312.jpg')
        self.manifest = self.root/'manifest.json'
        builder.write_json(self.manifest, {'images_dir': str(self.root/'images'), 'pages': [self.entry]})

    def tearDown(self): self.temp.cleanup()

    def inputs(self, entry=None, impl='implementation-v1'):
        return builder.page_inputs(self.manifest, entry or self.entry, self.root/'images', impl, self.reviews)

    def test_new_status_source_implementation_and_review_invalidate(self):
        original = self.inputs()[1]
        self.assertEqual(self.inputs()[1], original)
        self.assertNotEqual(self.inputs({**self.entry,'status':'final'})[1], original)
        self.assertNotEqual(self.inputs(impl='implementation-v2')[1], original)
        source = self.root/'annotations/0312.gj'; source.write_text(source.read_text()+'\n// verified\n')
        self.assertNotEqual(self.inputs()[1], original)
        inputs = self.inputs()[0]; self.reviews.mkdir()
        review = {k: inputs[k] for k in ('source_sha256','image_sha256')}
        builder.write_json(self.reviews/'0312.json', review)
        self.assertNotEqual(self.inputs()[1], original)
        source.write_text(source.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'stale'): self.inputs()

    def test_artifact_damage_is_not_skipped(self):
        p = self.root/'artifact'; p.mkdir(); (p/'a.txt').write_text('abc')
        record = {'path':'artifact','artifacts':{'a.txt':builder.digest(p/'a.txt')}}
        self.assertTrue(builder.intact(self.root,record))
        (p/'a.txt').write_text('changed')
        self.assertFalse(builder.intact(self.root,record))
        (p/'a.txt').unlink()
        self.assertFalse(builder.intact(self.root,record))

    def test_review_merge_and_stale_import_are_safe(self):
        inputs = self.inputs()[0]
        base = {k: inputs[k] for k in ('source_sha256','image_sha256')}
        first = {**base,'band_bboxes':{'p0312-b0':[800,160,1000,1500]}}
        path = self.root/'review.json'
        builder.write_json(path, {'schema':'guji-ocr-review/1','pages':{'312':first}})
        builder.import_reviews(path,self.manifest,self.root/'images',self.reviews)
        second = {**base,'region_bboxes':{'p0312-b0-e0':[900,200,1000,300]}}
        builder.write_json(path, {'schema':'guji-ocr-review/1','pages':{'312':second}})
        builder.import_reviews(path,self.manifest,self.root/'images',self.reviews)
        before = (self.reviews/'0312.json').read_bytes()
        self.assertIn('p0312-b0',builder.read_json(self.reviews/'0312.json')['band_bboxes'])
        second['source_sha256']='outdated'
        builder.write_json(path, {'schema':'guji-ocr-review/1','pages':{'312':second}})
        with self.assertRaisesRegex(ValueError,'Stale'): builder.import_reviews(path,self.manifest,self.root/'images',self.reviews)
        self.assertEqual((self.reviews/'0312.json').read_bytes(), before)

    def test_status_downgrade_removes_active_without_deleting_objects(self):
        output = self.root/'output'; output.mkdir(); (output/'retained').mkdir(); (output/'retained/data').write_text('old')
        builder.write_json(output/'manifest.json', {'pages':[{'page':312,'path':'retained'}]})
        self.entry['status']='draft';builder.write_json(self.manifest, {'images_dir':str(self.root/'images'),'pages':[self.entry]})
        args=argparse.Namespace(manifest=self.manifest,output=output,images_dir=None,review_dir=self.reviews,import_review=None,pages=None,force=False)
        with patch.object(builder,'implementation_fingerprint',return_value={}): self.assertEqual(builder.build(args),0)
        self.assertEqual(builder.read_json(output/'manifest.json')['pages'],[])
        self.assertTrue((output/'retained/data').exists())


if __name__ == '__main__': unittest.main()
