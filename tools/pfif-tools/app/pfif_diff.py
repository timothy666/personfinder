#!/usr/bin/env python
# Copyright 2011 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Displays the difference between two PFIF XML files.

* Differences in field order are ignored regardless of PFIF version.
* Notes that are children of persons automatically have the person_record_id
  added to them, so children of persons and top-level notes are considered the
  same.
* This tool assumes that both files are valid PFIF XML.  That means that this
  tool is not guaranteed to notice if, for instance, one file has a child of the
  root that is neither a person nor a note and the other child is missing that
  or if there are two notes with the same note_record_id.
* The output will include one message per person or note that is missing or
  added.  These messages will specify whether it is a person or note and whether
  it was missing or added in addition to the id of the note.  The output will
  also include one message per person or note field that is missing, added, or
  changed.  For each of these, it will display the id of the containing person
  or note, the field name, whether the field was missing, added, or changed, the
  current text (if present), and the expected text (if present)."""

__author__ = 'samking@google.com (Sam King)'

import utils
import optparse

# TODO(samking): Add line numbers and xml lines.

# To allow person_record_ids and note_record_ids (which could be the same) to
# reside in the same map, we need to make them unique.
PERSON_PREFIX = 'p'
NOTE_PREFIX = 'n'

def record_id_to_key(record_id, is_person):
  """Call this method on a record_id to turn the record id into a key for the
  object generated by objectify_pfif_xml.  This must be done to allow both
  notes and persons to reside in the same map."""
  if is_person:
    return PERSON_PREFIX + record_id
  else:
    return NOTE_PREFIX + record_id

def is_key_person(key):
  """Returns True if the key corresponds to a person or False if the key
  corresponds to a note."""
  return key.startswith(PERSON_PREFIX)

def key_to_record_id(key):
  """Undoes record_id_to_key."""
  # This function will need to change if the prefixes are more than 1 character
  assert len(PERSON_PREFIX) == 1 and len(NOTE_PREFIX) == 1
  return key[1:]

def change_record_ids(reference_map):
  """Call this method on a map to transform all keys as per record_id_to_key.
  This can change a reference map into a map suitable for comparison with a map
  generated by objectify_pfif_xml."""
  transformed_object = {}
  for record_id, record_map in reference_map.items():
    is_person = 'person' in record_id
    transformed_key = record_id_to_key(record_id, is_person)
    transformed_object[transformed_key] = record_map
  return transformed_object


def objectify_parents(parents, is_person, object_map, tree,
                      parent_person_record_id=None, ignore_fields=None,
                      omit_blank_fields=False):
  """Adds the object representation of each parent in parents to object_map.
  If is_person, all parents are assumed to be persons (else, notes).  Tree is
  a PfifXmlTree.  Specifying parent_person_record_id is used for recursive
  calls when a person has a note as a child.  Any fields in ignore_fields will
  not be added to object_map."""
  if ignore_fields is None:
    ignore_fields = []
  if is_person:
    record_id_tag = 'person_record_id'
  else:
    record_id_tag = 'note_record_id'
  for parent in parents:
    record_id = tree.get_field_text(parent, record_id_tag)
    if record_id is None:
      # TODO(samking): better handling of this error?
      print 'Invalid PFIF XML: a record is missing its ' + record_id_tag
    else:
      record_map = object_map.setdefault(
          record_id_to_key(record_id, is_person), {})
      # If this note is a child of a person, it isn't required to have a
      # person_record_id, but it's easier to deal with notes that have
      # person_record_ids, so we force-add it.
      if (not is_person and parent_person_record_id is not None and
          'person_record_id' not in ignore_fields):
        record_map['person_record_id'] = parent_person_record_id
      for child in parent.getchildren():
        field_name = utils.extract_tag(child.tag)
        # Don't add any ignored fields.  Also, we'll deal with notes together,
        # so skip them.
        if (field_name not in ignore_fields) and (not is_person or field_name !=
                                                  'note'):
          # if there is no text in the node, use the empty string, not None
          field_value = child.text or ''
          # Add the record unless field_value is blank and omit_blank_fields
          if field_value or not omit_blank_fields:
            record_map[field_name] = field_value
      if is_person:
        sub_notes = parent.findall(tree.add_namespace_to_tag('note'))
        objectify_parents(sub_notes, False, object_map, tree,
                          parent_person_record_id=record_id,
                          ignore_fields=ignore_fields,
                          omit_blank_fields=omit_blank_fields)

def objectify_pfif_xml(file_to_objectify, ignore_fields=None,
                       omit_blank_fields=False):
  """Turns a file of PFIF XML into a map."""
  # read the file into an XML tree
  tree = utils.PfifXmlTree(file_to_objectify)
  # turn the xml trees into a persons and notes map for each file.  They will
  # map from record_id to a map from field_name to value
  object_map = {}
  objectify_parents(tree.get_all_persons(), True, object_map, tree,
                    ignore_fields=ignore_fields,
                    omit_blank_fields=omit_blank_fields)
  objectify_parents(tree.get_top_level_notes(), False, object_map, tree,
                    ignore_fields=ignore_fields,
                    omit_blank_fields=omit_blank_fields)
  return object_map

def make_diff_message(category, record_id, extra_data=None, xml_tag=None):
  """Returns a Message object with the provided information."""
  is_person = is_key_person(record_id)
  real_record_id = key_to_record_id(record_id)
  if is_person:
    return utils.Message(category, extra_data=extra_data, xml_tag=xml_tag,
                         person_record_id=real_record_id)
  else:
    return utils.Message(category, extra_data=extra_data, xml_tag=xml_tag,
                         note_record_id=real_record_id)

def pfif_obj_diff(records_a, records_b, text_is_case_sensitive):
  """Compares if records_a and records_b contain the same data.  Returns a
  list of messages containing one message for each of the following scenarios:
   * Deleted Records: records_a contains a record that is not in records_b,
   * Added Records: records_b contains a record that is not in records_a,
   * Deleted Fields: a record in records_a contains a field that is not in the
     corresponding record in records_b
   * Added Fields: a record in records_b contains a field that is not in the
     corresponding record in records_a
   * Changed Values: a field value in records_a is not the same as the
     corresponding field value in records_b"""
  messages = []
  for record, field_map_a in records_a.items():
    field_map_b = records_b.get(record)
    if field_map_b is None:
      messages.append(make_diff_message(utils.Categories.DELETED_RECORD,
                                        record))
    else:
      for field, value_a in field_map_a.items():
        value_b = field_map_b.get(field)
        if value_b is None:
          messages.append(make_diff_message(utils.Categories.DELETED_FIELD,
                                            record, xml_tag=field))
        else:
          if not text_is_case_sensitive:
            value_a = value_a.lower()
            value_b = value_b.lower()
          if value_a != value_b:
            extra_data = 'A:"' + value_a + '" is now B:"' + value_b + '"'
            messages.append(make_diff_message(utils.Categories.CHANGED_FIELD,
                                              record, extra_data=extra_data,
                                              xml_tag=field))
      for field in field_map_b:
        if field not in field_map_a:
          messages.append(make_diff_message(utils.Categories.ADDED_FIELD,
                                            record, xml_tag=field))
  for record in records_b:
    if record not in records_a:
      messages.append(make_diff_message(utils.Categories.ADDED_RECORD, record))
  return messages

def pfif_file_diff(file_a, file_b, text_is_case_sensitive=True,
                   ignore_fields=None, omit_blank_fields=False):
  """Compares file_a and file_b.  Returns a list of messages as per
  pfif_obj_diff."""
  records_a = objectify_pfif_xml(file_a, ignore_fields=ignore_fields,
                                 omit_blank_fields=omit_blank_fields)
  records_b = objectify_pfif_xml(file_b, ignore_fields=ignore_fields,
                                 omit_blank_fields=omit_blank_fields)
  return pfif_obj_diff(records_a, records_b, text_is_case_sensitive)

def main():
  """Prints a diff between two files."""
  parser = optparse.OptionParser(usage='usage: %prog file-a file-b [options]')
  parser.add_option('--text-is-case-insensitive', action='store_false',
                    dest='text_is_case_sensitive',  default=True,
                    help='<pfif:full_name>Jane</pfif:full_name> is the same as '
                    '<pfif:full_name>JANE</pfif:full_name>')
  parser.add_option('--no-grouping', action='store_false',
                    default=True, dest='group_by_record_id',
                    help='Rather than grouping all differences pertaining to '
                    'the same record together, every difference will be '
                    'displayed individually.')
  parser.add_option('--ignore-field', action='append', dest='ignore_fields',
                    default=[], help='--ignore-field photo_url will mean that '
                    'there will be no messages for photo_url fields that are '
                    'added, removed, or changed.  To specify multiple fields '
                    'to ignore, use this flag multiple times.')
  parser.add_option('--omit-blank-fields', action='store_true', default=False,
                    help='Normally, a blank field (ie, <foo></foo>) will count '
                    'as a different against a file that does not have that '
                    'field at all.  If you pass this flag, a blank field will '
                    'count as an omitted field.')
  (options, args) = parser.parse_args()

  assert len(args) >= 2, 'Must provide two files to diff.'
  messages = pfif_file_diff(
      utils.open_file(args[0]), utils.open_file(args[1]),
      text_is_case_sensitive=options.text_is_case_sensitive,
      ignore_fields=options.ignore_fields,
      omit_blank_fields=options.omit_blank_fields)
  print utils.MessagesOutput.generate_message_summary(messages, is_html=False)
  if options.group_by_record_id:
    print utils.MessagesOutput.messages_to_str_by_id(messages)
  else:
    print utils.MessagesOutput.messages_to_str(messages)

if __name__ == '__main__':
  main()