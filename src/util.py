def selective_merge(base_obj, delta_obj, restrict_keys=False):
    """
    Recursively merge dict delta_obj into base_obj by adding all key/value
    pairs which don't exist in base_obj yet, optionally removing all keys from
    base_obj which are not in delta_obj.
    """
    if not isinstance(base_obj, dict):
        return base_obj

    delta_keys = set(delta_obj)
    base_keys = set(base_obj)
    common_keys = base_keys & delta_keys
    new_keys = delta_keys - common_keys
    # only use keys not present in delta_obj if restrict_keys is False
    base_keys_to_copy = set() if restrict_keys else (base_keys - common_keys)

    ret = {
        # keys only in base_obj and not in delta_obj
        **{
            k: base_obj[k]
            for k in base_keys_to_copy
        },
        # keys in both base_obj and delta_obj
        **{
            k: selective_merge(base_obj[k], delta_obj[k], restrict_keys)
            for k in common_keys
        },
        # keys only in delta_obj
        **{
            k: delta_obj[k]
               if not isinstance(delta_obj[k], dict)
               # make deep copies of nested dicts
               else selective_merge(dict(), delta_obj[k])
            for k in new_keys
        }
    }

    return ret


def restrict_keys(template: dict, target: dict):
    """
    Return a new sub-dict based on target containing only keys which are also present in template
    """
    return {
        key: value
        for key, value in target.items()
        if key in template
    }


def split(data, pred):
    """
    Partition an iterable in two sublists with the first containing all items for which
    the given predicate returned True and the second containing all other items
    """
    yes, no = [], []
    for d in data:
        if pred(d):
            yes.append(d)
        else:
            no.append(d)
    return (yes, no)