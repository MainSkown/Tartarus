from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Lists and nullable fields are required in the OpenAPI schema, so the generated client
    never has to guess whether a missing key means empty."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
