"""Repair skinCluster bind matrices after a Blender -> FBX -> Maya import.

The symptom is a model that looks subtly wrong -- limbs rotated, fingers
splayed into spikes -- while the vertex data is actually perfect. Proof:
switching the skinCluster envelope to 0 snaps the mesh back to exactly the
source positions.

The cause is ``bindPreMatrix``. Maya deforms a vertex by

    world = sum_i  weight_i * (bindPreMatrix_i * jointWorld_i)

so bindPreMatrix must be the inverse of each joint's world matrix *at bind
time*. Blender's FBX writes bind data the importer does not always reconstruct;
on this rig the worst joint was off by 343 cm, larger than the character.

Since the source armature is at rest, the joints as imported already are the
bind pose, so rewriting each bindPreMatrix as the inverse of the joint's
current world matrix makes the skin a no-op at the current pose -- restoring
the silhouette exactly -- while every painted weight is left untouched.

    mayapy tools/fix_fbx_bind.py <scene.mb> [-o out.mb]
"""

import argparse
import os
import sys


def repair(verbose=True):
    """Rewrite bindPreMatrix on every skinCluster. Returns per-node stats."""
    from maya import cmds
    import maya.api.OpenMaya as om

    report = []
    for skin in cmds.ls(type="skinCluster") or []:
        indices = cmds.getAttr(skin + ".matrix", multiIndices=True) or []
        worst_before = 0.0
        fixed = 0

        for index in indices:
            joint = cmds.listConnections("%s.matrix[%d]" % (skin, index),
                                         source=True, destination=False)
            if not joint:
                continue
            joint = joint[0]

            plug = "%s.bindPreMatrix[%d]" % (skin, index)
            # A connected bindPreMatrix is driven elsewhere; setAttr would fail.
            for src in cmds.listConnections(plug, source=True, destination=False,
                                            plugs=True) or []:
                cmds.disconnectAttr(src, plug)

            current = om.MMatrix(cmds.getAttr(plug))
            world = om.MMatrix(cmds.getAttr(joint + ".worldMatrix[0]"))
            delta = current * world
            worst_before = max(
                worst_before,
                om.MVector(delta[12], delta[13], delta[14]).length())

            cmds.setAttr(plug,
                         cmds.getAttr(joint + ".worldInverseMatrix[0]"),
                         type="matrix")
            fixed += 1

        report.append((skin, fixed, worst_before))
        if verbose:
            print("  %-16s influences=%-5d worst bind offset was %8.3f cm"
                  % (skin, fixed, worst_before))

    # The stored bind pose describes the same thing and is now stale.
    joints = cmds.ls(type="joint") or []
    for pose in cmds.ls(type="dagPose") or []:
        cmds.delete(pose)
    if joints:
        cmds.select(joints, replace=True)
        cmds.dagPose(save=True, bindPose=True)
        cmds.select(clear=True)
        if verbose:
            print("  bind pose rebuilt from %d joints" % len(joints))

    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", help="Maya file to repair")
    parser.add_argument("-o", "--output", help="write here instead of in place")
    args = parser.parse_args(argv)

    import maya.standalone
    maya.standalone.initialize(name="python")
    from maya import cmds

    cmds.file(args.scene, open=True, force=True)
    print("opened", args.scene)

    report = repair()
    if not report:
        print("no skinClusters found -- nothing to do")
        return 1

    out = args.output or args.scene
    cmds.file(rename=out)
    cmds.file(save=True, type="mayaBinary", force=True)
    print("saved %s (%.1f MB)" % (out, os.path.getsize(out) / 1048576.0))

    maya.standalone.uninitialize()
    return 0


if __name__ == "__main__":
    sys.exit(main())
