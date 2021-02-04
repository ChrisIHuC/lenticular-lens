from psycopg2 import sql as psycopg2_sql

from ll.util.helpers import get_string_from_sql
from ll.util.hasher import hash_string_min, column_name_hash


class PropertyField:
    def __init__(self, data, ets, transformers=None):
        self._data = data if isinstance(data, list) else [data]
        self._transformers = transformers if transformers else []

        if ets:
            self._collection = ets.collection
            self._alias = ets.alias
            self._columns = ets.columns

        self._extend = True
        self._hash = None
        self._prop_path = None

    def no_extend(self):
        self._extend = False

    @property
    def property_path(self):
        return self._data

    @property
    def resource_label(self):
        if not self._intermediate_property_path:
            return self._alias

        return self._intermediate_property_path[-1]['alias']

    @property
    def prop_name(self):
        return self._data[-1]

    @property
    def prop_label(self):
        return column_name_hash(self.prop_name)

    @property
    def extended_prop_label(self):
        return hash_string_min(self.resource_label + '.' + self.prop_label) + '_extended'

    @property
    def is_list(self):
        if self.prop_label in self._columns:
            return self._columns[self.prop_label]['isList']

        return False

    @property
    def sql(self):
        sql = self.get_property_sql(self.resource_label, self.prop_label, self._extend and self.is_list)

        for transformer in self._transformers:
            template_sql = psycopg2_sql.SQL(transformer['sql_template'])
            sql_parameters = {key: psycopg2_sql.Literal(value) for (key, value) in transformer['parameters'].items()}
            sql = template_sql.format(property=sql, **sql_parameters)

        return sql

    def add_joins(self, joins):
        cur_resource = self._alias
        cur_columns = self._columns
        for prop_in_path in self._intermediate_property_path:
            next_table_name = prop_in_path['table_name']
            next_resource = prop_in_path['alias']
            is_list = cur_columns[prop_in_path['property']]['isList']

            if is_list:
                extended_prop_alias = self.get_extended_property_alias(cur_resource, prop_in_path['property'])
                joins.add_join(psycopg2_sql.SQL(
                    'LEFT JOIN unnest({alias}.{column_name}) ' +
                    'AS {column_name_expanded} ON true'
                ).format(
                    alias=psycopg2_sql.Identifier(cur_resource),
                    column_name=psycopg2_sql.Identifier(prop_in_path['property']),
                    column_name_expanded=psycopg2_sql.Identifier(extended_prop_alias)
                ), extended_prop_alias)

            lhs = self.get_property_sql(cur_resource, prop_in_path['property'], is_list)
            rhs = self.get_property_sql(next_resource, 'uri')

            joins.add_join(psycopg2_sql.SQL('LEFT JOIN timbuctoo.{target} AS {alias} \nON {lhs} = {rhs}').format(
                target=psycopg2_sql.Identifier(next_table_name),
                alias=psycopg2_sql.Identifier(next_resource),
                lhs=lhs, rhs=rhs
            ), next_resource)

            cur_resource = next_resource
            cur_columns = prop_in_path['columns']

        if self.is_list:
            joins.add_join(psycopg2_sql.SQL(
                'LEFT JOIN unnest({alias}.{column_name}) ' +
                'AS {column_name_expanded} ON true'
            ).format(
                alias=psycopg2_sql.Identifier(self._alias),
                column_name=psycopg2_sql.Identifier(self.prop_label),
                column_name_expanded=psycopg2_sql.Identifier(self.extended_prop_label)
            ), self.extended_prop_label)

    @property
    def collections_required(self):
        return set([prop_in_path['table_info']['collection_id'] for prop_in_path in self._prop_path])

    @property
    def is_downloaded(self):
        if self._collection.rows_downloaded > -1:
            return False

        for prop_in_path in self._intermediate_property_path:
            if not prop_in_path['downloaded']:
                return False

        return True

    @property
    def hash(self):
        if not self._hash:
            self._hash = hash_string_min(get_string_from_sql(self.sql))
        return self._hash

    @property
    def _intermediate_property_path(self):
        if not self._prop_path:
            self._prop_path = []
            path = ''

            for (prop, collection_id) in [(self._data[i], self._data[i + 1]) for i in range(0, len(self._data) - 2, 2)]:
                table_data = None
                downloaded = False
                if collection_id in self._collection.dataset_table_data:
                    table_data = self._collection.dataset_table_data[collection_id]
                    downloaded = table_data['update_finish_time'] \
                                 and table_data['update_finish_time'] >= table_data['update_start_time']
                    path += table_data['table_name']

                self._prop_path.append({
                    'table_name': table_data['table_name'] if table_data else None,
                    'columns': table_data['columns'] if table_data else None,
                    'alias': hash_string_min(path),
                    'property': column_name_hash(prop),
                    'downloaded': downloaded
                })

        return self._prop_path

    @staticmethod
    def get_extended_property_alias(resource, prop):
        return hash_string_min(resource + '.' + prop) + '_extended'

    @staticmethod
    def get_property_sql(resource, prop, extend=False):
        absolute_property = [PropertyField.get_extended_property_alias(resource, prop)] \
            if extend else [resource, prop]
        return psycopg2_sql.SQL('.').join(map(psycopg2_sql.Identifier, absolute_property))

    def __eq__(self, other):
        return isinstance(other, PropertyField) and self.hash == other.hash

    def __hash__(self):
        return hash(self.hash)