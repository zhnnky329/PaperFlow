"""Collection hierarchy shared by the API and Finder synchronization."""

MAX_COLLECTION_DEPTH = 32


class CollectionTreeError(ValueError):
    pass


def collection_path(row, rows_by_id):
    parts, seen = [], set()
    while row is not None:
        if row.id in seen:
            raise CollectionTreeError("文件夹不能形成循环")
        seen.add(row.id)
        parts.append(row.name)
        if len(parts) > MAX_COLLECTION_DEPTH:
            raise CollectionTreeError(f"文件夹最多支持 {MAX_COLLECTION_DEPTH} 层")
        if row.parent_id is None:
            break
        row = rows_by_id.get(row.parent_id)
        if row is None:
            raise CollectionTreeError("上级文件夹不存在")
    return "/".join(reversed(parts))


def collection_descendants(item_id, rows_by_id):
    children = {}
    for row in rows_by_id.values():
        children.setdefault(row.parent_id, []).append(row.id)
    result, pending = set(), [item_id]
    while pending:
        current = pending.pop()
        if current not in result:
            result.add(current)
            pending.extend(children.get(current, ()))
    return result


def collection_info(row, rows_by_id):
    path = collection_path(row, rows_by_id)
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "path": path,
        "depth": path.count("/"),
    }
