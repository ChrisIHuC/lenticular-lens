from uuid import uuid4
from os.path import commonprefix
from psycopg2 import sql as psycopg2_sql

from ll.util.hasher import column_name_hash
from ll.util.config_db import db_conn, fetch_many

from ll.worker.job import WorkerJob
from ll.data.timbuctoo import Timbuctoo


class TimbuctooJob(WorkerJob):
    def __init__(self, table_name, graphql_endpoint, hsid, dataset_id, collection_id,
                 columns, cursor, rows_count, rows_per_page):
        self._table_name = table_name
        self._graphql_endpoint = graphql_endpoint
        self._hsid = hsid
        self._dataset_id = dataset_id
        self._collection_id = collection_id
        self._columns = columns
        self._cursor = cursor
        self._rows_count = rows_count
        self._rows_per_page = rows_per_page
        self._namespaces = []

        super().__init__(self.run_process)

    @staticmethod
    def format_query(column_info):
        if column_info['name'] == 'uri':
            return ''

        result = ''
        if column_info['isValueType']:
            result = '... on Value { value } '
        if column_info['isLink']:
            result += '... on Entity { uri }'  # It might be both a value and a link
        if column_info['isList']:
            result = 'items { ' + result + ' }'

        return '{ ' + result + ' }'

    @staticmethod
    def extract_value(value):
        if not value or isinstance(value, str):
            return value

        if 'items' in value and value['items']:
            return [TimbuctooJob.extract_value(item) for item in value['items']]

        if 'value' in value:
            return value['value']

        if 'uri' in value:
            return value['uri']

        return None

    def run_process(self):
        self.download()
        self.determine_namespaces()

    def download(self):
        total_insert = 0

        while total_insert == 0 or self._cursor:
            columns = [self._columns[name]['name'] + self.format_query(self._columns[name]) for name in self._columns]

            query = """
                query fetch($cursor: ID) {{
                    dataSets {{
                        {dataset} {{
                            {list_id}(cursor: $cursor, count: {count}) {{
                                nextCursor
                                items {{
                                    {columns}
                                }}
                            }}
                        }}
                    }}
                }}
            """.format(
                dataset=self._dataset_id,
                list_id=self._collection_id + 'List',
                count=self._rows_per_page,
                columns="\n".join(columns)
            )

            query_result = Timbuctoo(self._graphql_endpoint, self._hsid).fetch_graph_ql(query, {'cursor': self._cursor})
            if not query_result:
                return

            query_result = query_result['dataSets'][self._dataset_id][self._collection_id + 'List']

            # Property names can be too long for column names in Postgres, so make them shorter
            # We use hashing, because that keeps the column names unique and uniform
            results = [
                {column_name_hash(name): self.extract_value(item[name]) for name in item}
                for item in query_result['items']
            ]

            with self._db_conn.cursor() as cur:
                cur.execute("LOCK TABLE timbuctoo_tables IN ACCESS EXCLUSIVE MODE;")

                # Check if the data we have is still the data that is expected to be inserted
                cur.execute('''
                    SELECT 1
                    FROM timbuctoo_tables
                    WHERE "table_name" = %(table_name)s
                    AND (
                        %(next_page)s IS NULL AND next_page IS NULL
                        AND (update_finish_time IS NULL OR update_finish_time < update_start_time)
                    ) 
                    OR (
                        %(next_page)s IS NOT NULL AND next_page = %(next_page)s
                    )
                ''', {'table_name': self._table_name, 'next_page': self._cursor})

                if cur.fetchone() != (1,):
                    raise Exception('This is weird... '
                                    'Someone else updated the job for table %s '
                                    'while I was fetching data.' % self._table_name)

                cur.execute(psycopg2_sql.SQL('SELECT count(*) FROM timbuctoo.{}')
                            .format(psycopg2_sql.Identifier(self._table_name)))
                table_rows = cur.fetchone()[0]

                if table_rows != self._rows_count + total_insert:
                    raise Exception('Table %s has %i rows, expected %i. Quitting job.'
                                    % (self._table_name, table_rows, self._rows_count + total_insert))

                if len(results) > 0:
                    columns_sql = psycopg2_sql.SQL(', ').join(
                        [psycopg2_sql.Identifier(key) for key in results[0].keys()])

                    for result in results:
                        cur.execute(psycopg2_sql.SQL('INSERT INTO timbuctoo.{} ({}) VALUES %s').format(
                            psycopg2_sql.Identifier(self._table_name),
                            columns_sql,
                        ), (tuple(result.values()),))

                    total_insert += len(results)

                    cur.execute('''
                        UPDATE timbuctoo_tables
                        SET last_push_time = now(), next_page = %s, rows_count = %s
                        WHERE "table_name" = %s
                    ''', (query_result['nextCursor'], table_rows + len(results), self._table_name))

                self._db_conn.commit()

            self._cursor = query_result['nextCursor']

    def determine_namespaces(self):
        with self._db_conn.cursor(name=uuid4().hex) as cur:
            cur.execute(psycopg2_sql.SQL('SELECT uri FROM timbuctoo.{}')
                        .format(psycopg2_sql.Identifier(self._table_name)))

            for uri in fetch_many(cur):
                prefix_found = False

                for ns in self._namespaces:
                    common_prefix = commonprefix([uri[0], ns])

                    prefix_allowed = common_prefix != '' and common_prefix != 'http'
                    if common_prefix.startswith('http://') or common_prefix.startswith('https://'):
                        domain = common_prefix.replace('http://', '').replace('https://', '')
                        prefix_allowed = '/' in domain

                    if prefix_allowed:
                        prefix_found = True

                        if ns != common_prefix and ns.startswith(common_prefix):
                            self._namespaces.remove(ns)
                        if common_prefix not in self._namespaces:
                            self._namespaces.append(common_prefix)

                if not prefix_found:
                    self._namespaces.append(uri[0])

    def on_finish(self):
        if self._cursor is None:
            with db_conn() as conn, conn.cursor() as cur:
                cur.execute('UPDATE timbuctoo_tables '
                            'SET uri_namespaces = %s, update_finish_time = now() '
                            'WHERE "table_name" = %s', (self._namespaces, self._table_name,))

    def watch_process(self):
        pass

    def watch_kill(self):
        pass

    def on_kill(self, reset):
        pass

    def on_exception(self):
        pass
