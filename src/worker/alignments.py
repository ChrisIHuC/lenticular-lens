import re
import time
import gzip
import locale
import datetime
import threading

from os.path import join

from common.config_db import db_conn
from common.helpers import hasher, update_alignment_job, table_to_csv

from common.ll.LLData.CSV_Associations import CSV_ASSOCIATIONS_DIR

from psycopg2 import sql as psycopg2_sql, ProgrammingError
from worker.matching.linksets_collection import LinksetsCollection


class AlignmentJob:
    def __init__(self, job_id, alignment, status):
        self.job_id = job_id
        self.alignment = alignment
        self.status = status
        self.linksets_collection = LinksetsCollection(job_id=job_id, run_match=alignment)

    def run(self):
        thread = threading.Thread(target=self.linksets_collection.run)
        thread.start()

        while thread.is_alive():
            self.watch_process()
            time.sleep(1)

        if self.linksets_collection.has_queued_view:
            print('Job %s downloading.' % self.job_id)
            update_alignment_job(self.job_id, self.alignment, {'status': 'Downloading'})
        elif self.linksets_collection.exception:
            print('Job %s failed.' % self.job_id)
            err_message = str(self.linksets_collection.exception)
            update_alignment_job(self.job_id, self.alignment, {'status': 'FAILED: ' + err_message})
        else:
            thread = threading.Thread(target=self.write_alignment_to_file)
            thread.start()

            while thread.is_alive():
                time.sleep(1)

    def kill(self):
        update_alignment_job(self.job_id, self.alignment, {'status': self.status})

        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(psycopg2_sql.SQL('DROP SCHEMA {} CASCADE')
                        .format(psycopg2_sql.Identifier(f'job_{self.alignment}_{self.job_id}')))
            conn.commit()

    def watch_process(self):
        message = self.linksets_collection.status

        if message.startswith('Generating linkset '):
            view_name = re.search(r'(?<=Generating linkset ).+(?=.$)', message)[0]

            with db_conn() as conn, conn.cursor() as cur:
                try:
                    cur.execute(psycopg2_sql.SQL('SELECT last_value FROM {}.{}').format(
                        psycopg2_sql.Identifier('job_' + self.alignment + '_' + self.job_id),
                        psycopg2_sql.Identifier(view_name + '_count'),
                    ))
                except ProgrammingError:
                    return

                inserted = cur.fetchone()[0]
                conn.commit()

            inserted_message = '%s links found so far.' % locale.format_string('%i', inserted, grouping=True)
            print(inserted_message)
            update_alignment_job(self.job_id, self.alignment, {'status': inserted_message})
        else:
            print(message)
            update_alignment_job(self.job_id, self.alignment, {'status': message})

    def write_alignment_to_file(self):
        with db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(psycopg2_sql.SQL('SELECT count(*) FROM {}.{}').format(
                    psycopg2_sql.Identifier('job_' + self.alignment + '_' + self.job_id),
                    psycopg2_sql.Identifier(self.linksets_collection.view_name)))
                inserted = cur.fetchone()[0]

            with conn.cursor() as cur:
                cur.execute("UPDATE alignments SET links_count = %s WHERE job_id = %s AND alignment = %s",
                            (inserted, self.job_id, self.alignment))

        print("Generating CSVs")
        for match in self.linksets_collection.matches:
            if str(match.id) != str(self.alignment):
                continue

            columns = [psycopg2_sql.Identifier('source_uri'), psycopg2_sql.Identifier('target_uri')]
            if match.is_association:
                prefix = 'association'
            else:
                prefix = 'alignment'
                columns.append(psycopg2_sql.Identifier('__cluster_similarity'))

            filename = f'{prefix}_{hasher(self.job_id)}_alignment_{match.id}.csv.gz'

            print('Creating file ' + join(CSV_ASSOCIATIONS_DIR, filename))
            with gzip.open(join(CSV_ASSOCIATIONS_DIR, filename), 'wt') as csv_file:
                table_to_csv(f'job_{self.alignment}_{self.job_id}.{match.name}', columns, csv_file)

        print('Cleaning up.')
        print('Dropping schema.')

        with db_conn() as conn, conn.cursor() as cur:
            cur.execute(psycopg2_sql.SQL('DROP SCHEMA {} CASCADE')
                        .format(psycopg2_sql.Identifier(f'job_{self.alignment}_{self.job_id}')))
            conn.commit()

        print(f'Schema job_{self.job_id} dropped.')
        print('Cleanup complete.')
        print('Job %s finished.' % self.job_id)

        update_alignment_job(self.job_id, self.alignment,
                             {'status': 'Finished', 'finished_at': str(datetime.datetime.now())})