from .exceptions import JsonSchemaDefinitionException
from .draft07 import CodeGeneratorDraft07


class CodeGeneratorDraft2019(CodeGeneratorDraft07):
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._json_keywords_to_function.update((
            ('unevaluatedProperties', self.generate_unevaluated_properties),
        ))

    def generate_unevaluated_properties(self):
        """
        JSON Schema draft 2019-09 ``unevaluatedProperties``.

        This implementation tracks annotations from the requested 2019-09
        applicator keywords: ``properties``, ``patternProperties``, ``$ref``,
        ``allOf``, ``anyOf``, ``oneOf``, ``if``/``then``/``else``, and from
        nested ``unevaluatedProperties``. It intentionally does not turn on
        the remainder of the 2019-09 vocabulary.
        """
        unevaluated_definition = self._definition['unevaluatedProperties']
        if unevaluated_definition is True:
            self.create_variable_is_dict()
            with self.l('if {variable}_is_dict:'):
                with self.l('for {variable}_key in {variable}.keys():'):
                    self.l('{}.add({variable}_key)', self._evaluated_stack[-1])
            return

        self.create_variable_is_dict()
        with self.l('if {variable}_is_dict:'):
            self.l(
                '{variable}_unevaluated_keys = set({variable}.keys()) - set({})',
                self._evaluated_stack[-1],
            )
            if unevaluated_definition is False:
                with self.l('if {variable}_unevaluated_keys:'):
                    self.exc(
                        '{name} must not contain "+str({variable}_unevaluated_keys)+" properties',
                        rule='unevaluatedProperties',
                    )
            elif unevaluated_definition == {}:
                with self.l('for {variable}_key in {variable}_unevaluated_keys:'):
                    self.l('{}.add({variable}_key)', self._evaluated_stack[-1])
            elif isinstance(unevaluated_definition, dict):
                with self.l('for {variable}_key in {variable}_unevaluated_keys:'):
                    self.l('{variable}_value = {variable}.get({variable}_key)')
                    with self.evaluation_scope() as property_evaluated:
                        with self.evaluation_guard(
                            property_evaluated,
                            mark_to=self._evaluated_stack[-2],
                            mark_expression='{variable}_key',
                        ):
                            self.generate_func_code_block(
                                unevaluated_definition,
                                '{}_value'.format(self._variable),
                                '{}.{{{}_key}}'.format(self._variable_name, self._variable),
                                clear_variables=True,
                            )
            else:
                raise JsonSchemaDefinitionException('unevaluatedProperties must be object or boolean')
