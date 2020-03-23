from psycopg2 import sql as psycopg2_sql
from ll.job.matching_function import MatchingFunction


class Conditions:
    def __init__(self, data, type, job):
        self._data = data
        self._type = type
        self._job = job
        self._conditions_list = None

    @property
    def conditions_list(self):
        if not self._conditions_list:
            self._conditions_list = []
            for idx, item in enumerate(self._data):
                if 'conditions' in item and 'type' in item:
                    self._conditions_list.append(Conditions(item['conditions'], item['type'], self._job))
                else:
                    self._conditions_list.append(MatchingFunction(item, self._job))

        return self._conditions_list

    @property
    def conditions_sql(self):
        filter_sqls = []
        for condition in self.conditions_list:
            if isinstance(condition, MatchingFunction):
                filter_sqls.append(condition.sql.format(
                    field_name=psycopg2_sql.Identifier(condition.field_name), **condition.sql_parameters))
            else:
                filter_sqls.append(condition.conditions_sql)

        return psycopg2_sql.SQL('({})').format(psycopg2_sql.SQL(' %s ' % self._type).join(filter_sqls))

    @property
    def index_templates(self):
        return [matching_function.index_template for matching_function in self.matching_functions]

    @property
    def matching_functions(self):
        matching_functions = []
        for condition in self.conditions_list:
            if isinstance(condition, MatchingFunction):
                matching_functions.append(condition)
            else:
                matching_functions += condition.matching_functions

        return matching_functions
