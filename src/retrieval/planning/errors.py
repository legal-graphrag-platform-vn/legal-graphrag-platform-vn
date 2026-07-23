"""Typed failures at the async query-planner boundary."""


class QueryPlannerError(RuntimeError):
    pass


class QueryPlannerDependencyError(QueryPlannerError):
    pass


class QueryPlannerTimeoutError(QueryPlannerError):
    pass


class QueryPlannerInvalidPlanError(QueryPlannerError):
    pass
