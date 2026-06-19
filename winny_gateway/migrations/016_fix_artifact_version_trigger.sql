-- Fix a pre-existing VIGIL bug surfaced by the artifact canvas: the
-- snapshot_artifact_version() trigger inserted into a non-existent column
-- `created_by` (the artifact_versions column is `authored_by`), so EVERY
-- update that changed `canvas` failed and rolled back (silently — the gateway
-- swallows db errors). It never fired before because nothing updated the
-- canvas column until the post-meeting artifact feature.
-- Also guard against snapshotting a NULL canvas (artifact_versions.canvas is
-- NOT NULL — e.g. the first canvas edit of a text-only Studio artifact).
CREATE OR REPLACE FUNCTION public.snapshot_artifact_version()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
BEGIN
  IF OLD.canvas IS DISTINCT FROM NEW.canvas AND OLD.canvas IS NOT NULL THEN
    INSERT INTO artifact_versions (artifact_id, version, canvas, authored_by)
    VALUES (OLD.id, OLD.version, OLD.canvas, auth.uid());
    NEW.version = OLD.version + 1;
  END IF;
  RETURN NEW;
END;
$function$;
