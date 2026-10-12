"""Shared PointerProperty poll callbacks for feature PropertyGroups. No bpy.types classes here."""


def mesh_object_poll(self, obj):
    return obj.type == 'MESH'


def armature_object_poll(self, obj):
    return obj.type == 'ARMATURE'
