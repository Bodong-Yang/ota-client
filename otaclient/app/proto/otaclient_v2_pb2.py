# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: otaclient_v2.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from google.protobuf import duration_pb2 as google_dot_protobuf_dot_duration__pb2


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x12otaclient_v2.proto\x12\x0bOtaClientV2\x1a\x1egoogle/protobuf/duration.proto\"Q\n\x10UpdateRequestEcu\x12\x0e\n\x06\x65\x63u_id\x18\x01 \x01(\t\x12\x0f\n\x07version\x18\x02 \x01(\t\x12\x0b\n\x03url\x18\x03 \x01(\t\x12\x0f\n\x07\x63ookies\x18\x04 \x01(\t\";\n\rUpdateRequest\x12*\n\x03\x65\x63u\x18\x01 \x03(\x0b\x32\x1d.OtaClientV2.UpdateRequestEcu\"M\n\x11UpdateResponseEcu\x12\x0e\n\x06\x65\x63u_id\x18\x01 \x01(\t\x12(\n\x06result\x18\x02 \x01(\x0e\x32\x18.OtaClientV2.FailureType\"=\n\x0eUpdateResponse\x12+\n\x03\x65\x63u\x18\x01 \x03(\x0b\x32\x1e.OtaClientV2.UpdateResponseEcu\"$\n\x12RollbackRequestEcu\x12\x0e\n\x06\x65\x63u_id\x18\x01 \x01(\t\"?\n\x0fRollbackRequest\x12,\n\x03\x65\x63u\x18\x01 \x03(\x0b\x32\x1f.OtaClientV2.RollbackRequestEcu\"O\n\x13RollbackResponseEcu\x12\x0e\n\x06\x65\x63u_id\x18\x01 \x01(\t\x12(\n\x06result\x18\x02 \x01(\x0e\x32\x18.OtaClientV2.FailureType\"A\n\x10RollbackResponse\x12-\n\x03\x65\x63u\x18\x01 \x03(\x0b\x32 .OtaClientV2.RollbackResponseEcu\"\x0f\n\rStatusRequest\"\xf6\x04\n\x0eStatusProgress\x12/\n\x05phase\x18\x01 \x01(\x0e\x32 .OtaClientV2.StatusProgressPhase\x12\x1b\n\x13total_regular_files\x18\x02 \x01(\x04\x12\x1f\n\x17regular_files_processed\x18\x03 \x01(\x04\x12\x1c\n\x14\x66iles_processed_copy\x18\x04 \x01(\x04\x12\x1c\n\x14\x66iles_processed_link\x18\x05 \x01(\x04\x12 \n\x18\x66iles_processed_download\x18\x06 \x01(\x04\x12 \n\x18\x66ile_size_processed_copy\x18\x07 \x01(\x04\x12 \n\x18\x66ile_size_processed_link\x18\x08 \x01(\x04\x12$\n\x1c\x66ile_size_processed_download\x18\t \x01(\x04\x12\x34\n\x11\x65lapsed_time_copy\x18\n \x01(\x0b\x32\x19.google.protobuf.Duration\x12\x34\n\x11\x65lapsed_time_link\x18\x0b \x01(\x0b\x32\x19.google.protobuf.Duration\x12\x38\n\x15\x65lapsed_time_download\x18\x0c \x01(\x0b\x32\x19.google.protobuf.Duration\x12\x17\n\x0f\x65rrors_download\x18\r \x01(\x04\x12\x1f\n\x17total_regular_file_size\x18\x0e \x01(\x04\x12\x35\n\x12total_elapsed_time\x18\x0f \x01(\x0b\x32\x19.google.protobuf.Duration\x12\x16\n\x0e\x64ownload_bytes\x18\x10 \x01(\x04\"\xb3\x01\n\x06Status\x12&\n\x06status\x18\x01 \x01(\x0e\x32\x16.OtaClientV2.StatusOta\x12)\n\x07\x66\x61ilure\x18\x02 \x01(\x0e\x32\x18.OtaClientV2.FailureType\x12\x16\n\x0e\x66\x61ilure_reason\x18\x03 \x01(\t\x12\x0f\n\x07version\x18\x04 \x01(\t\x12-\n\x08progress\x18\x05 \x01(\x0b\x32\x1b.OtaClientV2.StatusProgress\"r\n\x11StatusResponseEcu\x12\x0e\n\x06\x65\x63u_id\x18\x01 \x01(\t\x12(\n\x06result\x18\x02 \x01(\x0e\x32\x18.OtaClientV2.FailureType\x12#\n\x06status\x18\x03 \x01(\x0b\x32\x13.OtaClientV2.Status\"X\n\x0eStatusResponse\x12+\n\x03\x65\x63u\x18\x01 \x03(\x0b\x32\x1e.OtaClientV2.StatusResponseEcu\x12\x19\n\x11\x61vailable_ecu_ids\x18\x02 \x03(\t*A\n\x0b\x46\x61ilureType\x12\x0e\n\nNO_FAILURE\x10\x00\x12\x0f\n\x0bRECOVERABLE\x10\x01\x12\x11\n\rUNRECOVERABLE\x10\x02*k\n\tStatusOta\x12\x0f\n\x0bINITIALIZED\x10\x00\x12\x0b\n\x07SUCCESS\x10\x01\x12\x0b\n\x07\x46\x41ILURE\x10\x02\x12\x0c\n\x08UPDATING\x10\x03\x12\x0f\n\x0bROLLBACKING\x10\x04\x12\x14\n\x10ROLLBACK_FAILURE\x10\x05*~\n\x13StatusProgressPhase\x12\x0b\n\x07INITIAL\x10\x00\x12\x0c\n\x08METADATA\x10\x01\x12\r\n\tDIRECTORY\x10\x02\x12\x0b\n\x07SYMLINK\x10\x03\x12\x0b\n\x07REGULAR\x10\x04\x12\x0e\n\nPERSISTENT\x10\x05\x12\x13\n\x0fPOST_PROCESSING\x10\x06\x32\xe7\x01\n\x10OtaClientService\x12\x43\n\x06Update\x12\x1a.OtaClientV2.UpdateRequest\x1a\x1b.OtaClientV2.UpdateResponse\"\x00\x12I\n\x08Rollback\x12\x1c.OtaClientV2.RollbackRequest\x1a\x1d.OtaClientV2.RollbackResponse\"\x00\x12\x43\n\x06Status\x12\x1a.OtaClientV2.StatusRequest\x1a\x1b.OtaClientV2.StatusResponse\"\x00\x42\x06\xa2\x02\x03OTAb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'otaclient_v2_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  DESCRIPTOR._serialized_options = b'\242\002\003OTA'
  _FAILURETYPE._serialized_start=1642
  _FAILURETYPE._serialized_end=1707
  _STATUSOTA._serialized_start=1709
  _STATUSOTA._serialized_end=1816
  _STATUSPROGRESSPHASE._serialized_start=1818
  _STATUSPROGRESSPHASE._serialized_end=1944
  _UPDATEREQUESTECU._serialized_start=67
  _UPDATEREQUESTECU._serialized_end=148
  _UPDATEREQUEST._serialized_start=150
  _UPDATEREQUEST._serialized_end=209
  _UPDATERESPONSEECU._serialized_start=211
  _UPDATERESPONSEECU._serialized_end=288
  _UPDATERESPONSE._serialized_start=290
  _UPDATERESPONSE._serialized_end=351
  _ROLLBACKREQUESTECU._serialized_start=353
  _ROLLBACKREQUESTECU._serialized_end=389
  _ROLLBACKREQUEST._serialized_start=391
  _ROLLBACKREQUEST._serialized_end=454
  _ROLLBACKRESPONSEECU._serialized_start=456
  _ROLLBACKRESPONSEECU._serialized_end=535
  _ROLLBACKRESPONSE._serialized_start=537
  _ROLLBACKRESPONSE._serialized_end=602
  _STATUSREQUEST._serialized_start=604
  _STATUSREQUEST._serialized_end=619
  _STATUSPROGRESS._serialized_start=622
  _STATUSPROGRESS._serialized_end=1252
  _STATUS._serialized_start=1255
  _STATUS._serialized_end=1434
  _STATUSRESPONSEECU._serialized_start=1436
  _STATUSRESPONSEECU._serialized_end=1550
  _STATUSRESPONSE._serialized_start=1552
  _STATUSRESPONSE._serialized_end=1640
  _OTACLIENTSERVICE._serialized_start=1947
  _OTACLIENTSERVICE._serialized_end=2178
# @@protoc_insertion_point(module_scope)
