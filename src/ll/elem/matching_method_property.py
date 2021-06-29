from psycopg2 import sql

from ll.job.property_field import PropertyField
from ll.util.helpers import get_json_from_file
from ll.util.hasher import hash_string_min


class MatchingMethodProperty:
    _transformers_info = get_json_from_file('transformers.json')

    def __init__(self, property, ets_id, job,
                 apply_transformers, method_transformers, property_transformers, property_transformer_first,
                 field_type_info, norm_template, norm_properties):
        self._property = property
        self._ets = job.get_entity_type_selection_by_id(ets_id)
        self._field_type_info = field_type_info
        self._norm_template = norm_template
        self._norm_properties = norm_properties

        self._transformers = []
        if apply_transformers:
            self._transformers = method_transformers.copy()
            if property_transformer_first:
                self._transformers = property_transformers.copy() + method_transformers.copy()
            else:
                self._transformers = method_transformers.copy() + property_transformers.copy()

        self.property_transformers = property_transformers

    @property
    def prop_original(self):
        return PropertyField(self._property, entity_type_selection=self._ets,
                             transformers=self._get_field_transformers(normalized=False))

    @property
    def prop_normalized(self):
        if not self._norm_template:
            return None

        return PropertyField(self._property, entity_type_selection=self._ets,
                             transformers=self._get_field_transformers(normalized=True))

    @property
    def prepare_sql(self):
        prepare_sqls = [
            sql.SQL('SELECT init_dictionary({key}, {dictionary}, {additional});').format(
                key=sql.Literal(hash_string_min((transformer['parameters']['dictionary'],
                                                 transformer['parameters']['additional']))),
                dictionary=sql.Literal(transformer['parameters']['dictionary']),
                additional=sql.SQL('ARRAY[{}]::text[]').format(
                    sql.SQL(', ').join(sql.Literal(additional)
                                       for additional in transformer['parameters']['additional'])
                ),
            )
            for transformer in self._transformers
            if transformer['name'] == 'STOPWORDS'
        ]

        if prepare_sqls:
            return sql.SQL('\n').join(prepare_sqls)

        return None

    def _get_field_transformers(self, normalized=False):
        field_transformers = self._transformers.copy()
        for transformer in field_transformers:
            if transformer['name'] in self._transformers_info:
                transformer['sql_template'] = self._transformers_info[transformer['name']]['sql_template']

                if transformer['name'] == 'STOPWORDS':
                    transformer['parameters']['key'] = hash_string_min((transformer['parameters']['dictionary'],
                                                                        transformer['parameters']['additional']))
            else:
                raise NameError('Transformer %s is not defined' % transformer['name'])

        if not self._field_type_info['type']:
            field_transformers.insert(0, {
                'sql_template': self._transformers_info['LOWERCASE']['sql_template'],
                'parameters': {}
            })

        if self._field_type_info['type'] == 'number':
            field_transformers.append({
                'sql_template': self._transformers_info['TO_NUMERIC_IMMUTABLE']['sql_template'],
                'parameters': {}
            })
        elif self._field_type_info['type'] == 'date':
            field_transformers.append({
                'sql_template': self._transformers_info['TO_DATE_IMMUTABLE']['sql_template'],
                'parameters': {'format': self._field_type_info['parameters']['format']}
            })

        if normalized:
            field_transformers.append({
                'sql_template': self._norm_template,
                'parameters': self._norm_properties
            })

        return field_transformers

    def __eq__(self, other):
        return isinstance(other, MatchingMethodProperty) and self.prop_original == other.prop_original

    def __hash__(self):
        return hash(self.prop_original.hash)
