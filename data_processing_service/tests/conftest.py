from unittest.mock import Mock

import pytest


@pytest.fixture
def fake_s3_client():
    client = Mock()
    paginator = client.get_paginator.return_value
    paginator.paginate.return_value = []
    return client
