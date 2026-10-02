from .draft07 import CodeGeneratorDraft07


class CodeGeneratorDraft2019(CodeGeneratorDraft07):
    """
    Partial implementation of JSON schema draft 2019-09.

    On top of draft-07 it supports:

     * ``unevaluatedProperties`` with evaluated-properties tracking through
       ``properties``, ``patternProperties``, ``additionalProperties``,
       ``$ref``, ``allOf``, ``anyOf``, ``oneOf`` and ``if``/``then``/``else``
       (failed branches of applicators do not mark properties as evaluated),
     * ``$ref`` next to sibling keywords (it no longer overrides them).

    Other draft 2019-09 features (``$recursiveRef``, ``$anchor``,
    ``unevaluatedItems``, ``dependentSchemas``, ``minContains``,
    ``maxContains``, ``vocabulary``, ...) are not implemented.
    """

    FORMAT_REGEXS = dict(CodeGeneratorDraft07.FORMAT_REGEXS, **{
        'uuid': r'^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\Z',
        # ISO 8601 duration from RFC 3339 Appendix A
        'duration': (
            r'^P(?!$)'
            r'(?:'
            r'[0-9]+W'
            r'|(?:[0-9]+Y)?(?:[0-9]+M)?(?:[0-9]+D)?(?:T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?)?'
            r')\Z'
        ),
    })

    # Keywords whose (in-place) application can evaluate object properties.
    EVALUATING_KEYWORDS = frozenset((
        'properties', 'patternProperties', 'additionalProperties',
        'unevaluatedProperties', 'allOf', 'anyOf', 'oneOf',
        'if', 'then', 'else', 'dependencies', '$ref',
    ))

    def generate_validation_function(self, uri, name):
        """
        Generate validation function for given uri with given name.

        Compared to older drafts, generated functions accept an optional
        ``evaluated`` set. When it is passed, the function adds names of all
        object properties it evaluated into it, so ``unevaluatedProperties``
        of the referring schema can see annotations from behind the ``$ref``.
        """
        self._validation_functions_done.add(uri)
        self.l('')
        with self._resolver.resolving(uri) as definition:
            with self.l('def {}(data, custom_formats={{}}, name_prefix=None, evaluated=None):', name):
                if not self._fast_fail:
                    self.l('errors = []')
                outer_scopes = self._evaluated_scopes
                self._evaluated_scopes = []
                try:
                    tracks_evaluated = (
                        isinstance(definition, dict)
                        and not self.EVALUATING_KEYWORDS.isdisjoint(definition)
                    )
                    if tracks_evaluated:
                        self.l('data_evaluated = set()')
                        self._evaluated_scopes.append(('data', 'data_evaluated'))
                    self.generate_func_code_block(definition, 'data', 'data', clear_variables=True)
                    if tracks_evaluated:
                        with self.l('if evaluated is not None:'):
                            self.l('evaluated.update(data_evaluated)')
                finally:
                    self._evaluated_scopes = outer_scopes
                if not self._fast_fail:
                    self.l('if errors: raise JsonSchemaValuesException(errors)')
                self.l('return data')

    def _generate_func_code_block(self, definition):
        if isinstance(definition, bool):
            return self.generate_boolean_schema()
        if 'unevaluatedProperties' not in definition:
            count = 0
            if '$ref' in definition:
                # Since draft 2019-09, $ref does not override sibling keywords.
                self.generate_ref()
                count += 1
            return count + self.run_generate_functions(definition)
        # unevaluatedProperties applies to properties not evaluated by any
        # adjacent keyword, so all sibling keywords (including $ref) have to
        # record evaluated properties into a fresh set first.
        scope_name = self._new_evaluated_scope_name()
        self.l('{} = set()', scope_name)
        self._evaluated_scopes.append((self._variable, scope_name))
        try:
            count = 0
            if '$ref' in definition:
                self.generate_ref()
                count += 1
            count += self.run_generate_functions(definition)
            self.generate_unevaluated_properties(scope_name)
            count += 1
        finally:
            self._evaluated_scopes.pop()
        # Everything evaluated here is evaluated for the enclosing schema too.
        parent_scope = self._current_evaluated_scope()
        if parent_scope is not None:
            self._merge_evaluated_scope(parent_scope, scope_name)
        return count

    def generate_unevaluated_properties(self, evaluated_scope):
        """
        Implementation of draft 2019-09 ``unevaluatedProperties``. The value
        can be a boolean or a schema applied to every property not evaluated
        by adjacent keywords.

        .. code-block:: python

            {
                'properties': {'key': {'type': 'number'}},
                'unevaluatedProperties': False,
            }

        Valid object is containing only the key 'key'.
        """
        unevaluated_definition = self._definition['unevaluatedProperties']
        self.create_variable_is_dict()
        with self.l('if {variable}_is_dict:'):
            if unevaluated_definition is True:
                # Every unevaluated property is evaluated by this keyword.
                self.l('{}.update({{variable}})'.format(evaluated_scope))
                return
            unevaluated_var = '{}_unevaluated{}'.format(
                self._variable, self._evaluated_scope_counter + 1,
            )
            self._evaluated_scope_counter += 1
            self.l('{} = set({{variable}}) - {}'.format(unevaluated_var, evaluated_scope))
            if unevaluated_definition is False:
                with self.l('if {}:', unevaluated_var):
                    self.exc(
                        '{name} must not contain "+str(' + unevaluated_var + ')+" properties',
                        rule='unevaluatedProperties',
                    )
            else:
                with self.l('for {variable}_key in {}:', unevaluated_var):
                    self.l('{variable}_value = {variable}[{variable}_key]')
                    self.generate_func_code_block(
                        unevaluated_definition,
                        '{}_value'.format(self._variable),
                        '{}.{{{}_key}}'.format(self._variable_name, self._variable),
                    )
                # Properties the subschema was applied to are evaluated now.
                self._merge_evaluated_scope(evaluated_scope, unevaluated_var)
