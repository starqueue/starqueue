try:
    from .clean_field_pro import CleanField
except ImportError as e:
    from .clean_field_std import CleanField

clean_field = CleanField()


