try:
    import anymail
    print('anymail', getattr(anymail, '__version__', 'unknown'))
except Exception as e:
    print('error', e)
