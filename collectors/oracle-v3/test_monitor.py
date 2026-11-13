import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import archives
import monitor
import make_portal_config


def snapshot(applied=10, archived=12):
    return dict(dbid=3514081376, incarnation='1', resetlogs_time='2025-05-25 18:05:20',
                resetlogs_id=1202061920, header_count=16, bad_headers=0,
                applied_seq=applied, archived_seq=archived,
                applied_end_scn=str(applied*100), checkpoint_scn=str(applied*100))


def rows(a=10,b=12):
    return [dict(seq=s,first=str((s-1)*100),next=str(s*100),
                 first_max=str((s-1)*100),next_max=str(s*100)) for s in range(a+1,b+1)]


def receipt():
    return dict(size=10,sha256='a'*64,fingerprint=[1,2,10,4,5],verified_at=100)


class ArchiveTests(unittest.TestCase):
    def audit(self, available, manifest=None, applied=10, upper=12, persist=lambda m:None):
        return archives.audit(snapshot(applied,upper),snapshot(applied,upper),rows(applied,upper),
            manifest or {},verify=lambda seq,rid,old:receipt() if seq in available else None,
            persist=persist)

    def test_hole_below_max_is_counted(self):
        m,r,p=self.audit({10,12})
        result=archives.queue_metrics(m,r,p,10,12,present=lambda *a:True)
        self.assertEqual(result,dict(copied_seq=12,archive_gap=1,pending_apply=1))

    def test_last_verified_file_survives_applied_receipt_cleanup(self):
        manifest, _, _ = self.audit({10, 11, 12})
        self.assertEqual(manifest['last_verified_file']['name'], '1_12_1202061920.dbf')
        self.assertEqual(manifest['last_verified_file']['size_bytes'], 10)
        manifest, _, _ = self.audit(set(), manifest, applied=12, upper=12)
        self.assertEqual(manifest['last_verified_file']['sequence'], 12)
        self.assertEqual(manifest['receipts'], {})

    def test_old_manifest_backfills_file_without_new_archives(self):
        manifest, _, _ = self.audit({10, 11, 12})
        del manifest['last_verified_file']
        manifest, required, pending = self.audit({12}, manifest, applied=12, upper=12)
        self.assertEqual(manifest['last_verified_file']['name'], '1_12_1202061920.dbf')
        self.assertEqual(manifest['last_verified_file']['size_bytes'], 10)
        self.assertEqual(archives.queue_metrics(manifest, required, pending, 12, 12),
                         dict(copied_seq=12, archive_gap=0, pending_apply=0))

    def test_old_manifest_missing_file_does_not_invent_metadata(self):
        manifest, _, _ = self.audit({10, 11, 12})
        del manifest['last_verified_file']
        manifest, _, _ = self.audit(set(), manifest, applied=12, upper=12)
        self.assertNotIn('last_verified_file', manifest)
        self.assertEqual(manifest['copied_seq'], 12)

    def test_pending_deletion_is_counted_as_gap(self):
        m,r,p=self.audit({10,11,12})
        result=archives.queue_metrics(m,r,p,10,12,present=lambda seq,r:seq!=11)
        self.assertEqual(result['archive_gap'],1)
        self.assertEqual(result['pending_apply'],1)

    def test_applied_deletion_does_not_create_gap(self):
        m,r,p=self.audit({10,11,12})
        m,r,p=self.audit(set(),m,applied=12,upper=12)
        self.assertEqual(archives.queue_metrics(m,r,p,12,12),
                         dict(copied_seq=12,archive_gap=0,pending_apply=0))

    def test_no_bootstrap_copy_is_not_invented(self):
        m,r,p=self.audit(set(),applied=12,upper=12)
        self.assertIsNone(archives.queue_metrics(m,r,p,12,12)['copied_seq'])

    def test_missing_metadata_not_zero(self):
        with self.assertRaisesRegex(ValueError,'missing'):
            archives.validate_rows([],10,12,1000)

    def test_metadata_hole_below_max(self):
        with self.assertRaises(ValueError):
            archives.validate_rows(rows()[1:],10,12,1000)

    def test_scn_hole(self):
        r=rows();r[1]['first']='1101'
        with self.assertRaises(ValueError):
            archives.validate_rows(r,10,12,1000)

    def test_duplicate_metadata_conflict(self):
        r=rows();r[0]['next_max']='1101'
        with self.assertRaises(ValueError):
            archives.validate_rows(r,10,12,1000)

    def test_incarnation_cannot_reuse_receipts(self):
        m,_,_=self.audit({10})
        m['identity'][3]+=1
        with self.assertRaisesRegex(ValueError,'incarnation'):
            self.audit({11},m)

    def test_backward_apply_rejected(self):
        m,_,_=self.audit({10,11,12})
        with self.assertRaises(ValueError):
            self.audit(set(),m,applied=9)

    def test_receipt_persisted_before_next_copy_failure(self):
        saved=[]
        def check(seq,rid,old):
            if seq==12: raise OSError('read failure')
            return receipt()
        with self.assertRaises(OSError):
            archives.audit(snapshot(),snapshot(),rows(),{},verify=check,
                           persist=lambda m:saved.append(copy.deepcopy(m)))
        self.assertIn('11',saved[-1]['receipts'])

    def test_hash_comparison_and_cache(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);path=d/'1_11_1202061920.dbf';path.write_bytes(b'archive')
            origin=(7,hashlib.sha256(b'archive').hexdigest())
            r=archives.receipt_for(11,1202061920,directory=d,remote=lambda n:origin)
            self.assertIsNotNone(r)
            r2=archives.receipt_for(11,1202061920,r,directory=d,
                                   remote=lambda n:self.fail('unchanged receipt must not rehash source'))
            self.assertEqual(r2,r)
            path.write_bytes(b'corrupt')
            self.assertIsNone(archives.receipt_for(11,1202061920,r,directory=d,remote=lambda n:origin))

    def test_same_size_wrong_contents_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'1_11_1202061920.dbf').write_bytes(b'wrong')
            self.assertIsNone(archives.receipt_for(11,1202061920,directory=d,
                remote=lambda n:(5,hashlib.sha256(b'right').hexdigest())))

    def test_same_stat_fields_do_not_hide_rewritten_contents(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            path = directory / '1_11_1202061920.dbf'
            path.write_bytes(b'archive')
            origin = (7, hashlib.sha256(b'archive').hexdigest())
            with patch.object(archives, 'fingerprint', return_value=[1, 2, 7, 4, 5]):
                previous = archives.receipt_for(11, 1202061920, directory=directory,
                                                remote=lambda name: origin)
                path.write_bytes(b'corrupt')
                self.assertIsNone(archives.receipt_for(11, 1202061920, previous,
                                  directory=directory, remote=lambda name: origin))
                self.assertIsNone(archives.receipt_for(11, 1202061920, previous,
                                  directory=directory, remote=lambda name: None))

    def test_missing_source_not_adopted(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'1_11_1202061920.dbf').write_bytes(b'archive')
            self.assertIsNone(archives.receipt_for(11,1202061920,directory=d,remote=lambda n:None))

    def test_old_incarnation_filename_not_used(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);(d/'1_11_999.dbf').write_bytes(b'archive')
            self.assertIsNone(archives.receipt_for(11,1202061920,directory=d))


class CycleTests(unittest.TestCase):
    def cycle(self,transfer=0,apply=0,post=None,available=(10,11,12),fail_post=False):
        samples=iter([snapshot(),snapshot(),snapshot(),post or snapshot(12)])
        jobs=[]
        def execute(name,args):
            jobs.append((name,args))
            return transfer if name.startswith('sync') else apply
        def query(primary):
            if fail_post and len(jobs)==2: raise ValueError('SQL failure')
            return next(samples)
        result=monitor.cycle({},write=lambda d:None,query=query,execute=execute,clock=lambda:1000,
            read_manifest=lambda:{},write_manifest=lambda m:None,get_rows=lambda p,s:rows(),
            verify=lambda seq,rid,old:receipt() if seq in available else None,present=lambda *a:True)
        return result,jobs

    def test_success_all_eight_metrics(self):
        r,jobs=self.cycle()
        r=monitor.view(r,1000)
        self.assertEqual(r['cycle_ok'],1)
        self.assertTrue(all(r[k] is not None for k in monitor.KEYS))
        self.assertEqual((r['archive_gap'],r['pending_apply']),(0,0))
        self.assertEqual(jobs[0][1][-1],'1202061920')

    def test_transfer_failure_preserves_partial_receipts_without_recovery(self):
        r,jobs=self.cycle(transfer=1,available=(10,11))
        self.assertEqual(len(jobs),1)
        self.assertIsNone(r['apply_job'])
        self.assertEqual(r['transfer_job'],'failed')
        self.assertEqual((r['archive_gap'],r['pending_apply']),(1,1))

    def test_rman_failure_does_not_refresh_success_but_reports_partial_apply(self):
        r,_=self.cycle(apply=1,post=snapshot(11))
        self.assertIsNone(r['last_success_at'])
        self.assertEqual(r['apply_job'],'failed')
        self.assertEqual(r['applied_seq'],11)
        self.assertEqual(r['pending_apply'],1)

    def test_failed_post_sql_clears_provisional_metrics(self):
        r,_=self.cycle(fail_post=True)
        for key in ('applied_seq','copied_seq','archive_gap','pending_apply'):
            self.assertIsNone(r[key])
        self.assertEqual(r['cycle_ok'],0)

    def test_added_datafiles_after_apply(self):
        s = snapshot(12)
        s['header_count'] = 18
        r, _ = self.cycle(post=s)
        self.assertEqual(r['cycle_ok'], 1)
        self.assertEqual(r['applied_seq'], 12)

    def test_header_count_growth_and_safety(self):
        with patch.dict(monitor.PROFILE, header_count=16):
            s = snapshot(12)
            s['header_count'] = 18
            self.assertEqual(monitor.confirmed_applied(s), 12)
            s['bad_headers'] = 1
            with self.assertRaisesRegex(ValueError, 'bad_headers=1'):
                monitor.confirmed_applied(s)
            s['bad_headers'] = 0
            s['header_count'] = 15
            with self.assertRaisesRegex(ValueError, 'below verified baseline'):
                monitor.confirmed_applied(s)

    def test_bad_post_headers(self):
        s=snapshot(12);s['bad_headers']=1
        r,_=self.cycle(post=s)
        self.assertIsNone(r['applied_seq'])
        self.assertIsNone(r['last_success_at'])

    def test_missing_checkpoint(self):
        s=snapshot(12);s['checkpoint_scn']=None
        r,_=self.cycle(post=s)
        self.assertIsNone(r['applied_seq'])

    def test_post_snapshot_beyond_primary_clears_counters(self):
        r,_=self.cycle(post=snapshot(13))
        self.assertIsNone(r['archive_gap'])
        self.assertEqual(r['cycle_ok'],0)

    def test_old_source_not_refreshed_by_recent_json(self):
        r=monitor.view(dict(sampled_at=1000,source_sampled_at=100,apply_job='success'),now=1001)
        self.assertIsNone(r['apply_job'])
        self.assertEqual(r['cycle_ok'],0)


class PortalTests(unittest.TestCase):
    def data(self):
        return [dict(itemid=str(100+i),hostid='7',key_='db.replication.oracle.'+key)
                for i,key in enumerate(make_portal_config.KEYS)]

    def test_complete_mapping(self):
        pair=make_portal_config.build({'result':self.data()})['pairs'][0]
        self.assertEqual(set(pair['metrics']),set(monitor.KEYS))

    def test_missing_item_rejected(self):
        with self.assertRaises(ValueError): make_portal_config.build(self.data()[:-1])

    def test_duplicate_item_rejected(self):
        d=self.data();d.append(d[0])
        with self.assertRaises(ValueError): make_portal_config.build(d)

    def test_multiple_hosts_rejected(self):
        d=self.data();d[0]['hostid']='8'
        with self.assertRaises(ValueError): make_portal_config.build(d)


if __name__=='__main__':
    unittest.main()
