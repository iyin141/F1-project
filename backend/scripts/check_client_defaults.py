import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','f1_project.settings_test')
import django
django.setup()
from django.test.client import Client
from rest_framework.test import APIClient, APIRequestFactory

print('INTERNAL_API_KEY env:', os.environ.get('INTERNAL_API_KEY'))
print('Client.defaults present:', getattr(Client,'defaults',None))
print('APIClient.defaults present:', getattr(APIClient,'defaults',None))
print('APIRequestFactory class:', APIRequestFactory)
