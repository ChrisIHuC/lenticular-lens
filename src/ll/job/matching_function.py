import re
import json

from psycopg2 import sql as psycopg2_sql

from ll.data.property_field import PropertyField
from ll.util.helpers import hash_string, get_json_from_file


class MatchingFunction:
    _transformers = get_json_from_file('transformers.json')
    _matching_functions = get_json_from_file('matching_functions.json')

    def __init__(self, function_obj, job):
        self._data = function_obj
        self._job = job
        self._sources = []
        self._targets = []

        self.field_name = hash_string(json.dumps(function_obj))
        self._function_name = function_obj['method_name']
        self._parameters = function_obj['method_value']

        if self._function_name in self._matching_functions:
            self.function_info = self._matching_functions[self._function_name]
            if 'similarity' in function_obj:
                self.function_info['similarity'] = function_obj['similarity']
        else:
            raise NameError('Matching function %s is not defined' % self._function_name)

    @property
    def index_template(self):
        if 'index_using' not in self.function_info:
            return {}

        before_index = self.function_info.get('before_index', None)
        if before_index:
            before_index = psycopg2_sql.SQL(before_index)

        return {
            'template': self.function_info['index_using'],
            'field_name': self.field_name,
            'before_index': before_index,
        }

    @property
    def similarity_sql(self):
        if 'similarity' not in self.function_info or not self.function_info['similarity']:
            return None

        template = self.function_info['similarity']
        if isinstance(self.function_info['similarity'], str):
            template = re.sub(r'{source}', 'source.{field_name}', template)
            template = re.sub(r'{target}', 'target.{field_name}', template)

        return psycopg2_sql.SQL(template)

    @property
    def sql(self):
        template = self.function_info['sql_template']
        template = re.sub(r'{source}', 'source.{field_name}', template)
        template = re.sub(r'{target}', 'target.{field_name}', template)

        return psycopg2_sql.SQL(template)

    @property
    def sql_parameters(self):
        return {key: psycopg2_sql.Literal(value) for (key, value) in self._parameters.items()}

    @property
    def sources(self):
        if not self._sources:
            self._sources = self._get_entity_type_selections('sources')

        return self._sources

    @property
    def targets(self):
        if not self._targets:
            self._targets = self._get_entity_type_selections('targets')

        return self._targets

    def _get_entity_type_selections(self, key):
        entity_type_selections = {}
        for idx, entity_type_selection in self._data[key].items():
            entity_type_selections[idx] = []
            for field in entity_type_selection:
                field_transformers = field.get('transformers', [])

                for transformer in field_transformers:
                    if transformer['name'] in self._transformers:
                        transformer['transformer_info'] = self._transformers[transformer['name']]
                    else:
                        raise NameError('Transformer %s is not defined' % transformer['name'])

                property_field = PropertyField(field['property'], job=self._job, transformers=field_transformers)
                entity_type_selections[idx].append(property_field)

        return entity_type_selections
