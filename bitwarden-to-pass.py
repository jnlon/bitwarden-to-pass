#!/usr/bin/env python3

import os
import json
import re
import subprocess
from pathlib import Path

class BWItem:

	def __init__(self, json: dict):
		self.json = json

	def passname(self) -> str:
		id_head = self.json['id'].split('-')[0]
		name = self.json['name']
		name = re.sub('[-_|]', ' ', name)
		name = re.sub(' +', '-', name)
		return "{}-{}-{}".format(name.lower(), self.item_type(), id_head[0:4])

	def item_type(self):
		t = self.json['type']
		if   t == 1: return 'login'
		elif t == 2: return 'note'
		elif t == 3: return 'card'
		elif t == 4: return 'identity'
		else: raise Exception('Unknown item type: {}'.format(t))

	def format_card(card: dict) -> dict:
		d = {}
		d['Card Holder Name'] = card['cardholderName']
		d['Card Brand'] = card['brand']
		d['Card Number'] = card['number']
		d['Card Expire MM/YYYY'] = "{}/{}".format(card['expMonth'], card['expYear'])
		d['Card Security Code'] = card['code']
		return d

	def format_identity(identity: dict) -> dict:
		d = {}
		d['ID Title'] = identity['title']
		d['ID FirstName'] = identity['firstName']
		d['ID MiddleName'] = identity['middleName']
		d['ID LastName'] = identity['lastName']
		d['ID Address1'] = identity['address1']
		d['ID Address2'] = identity['address2']
		d['ID Address3'] = identity['address3']
		d['ID City'] = identity['city']
		d['ID State'] = identity['state']
		d['ID PostalCode'] = identity['postalCode']
		d['ID Country'] = identity['country']
		d['ID Company'] = identity['company']
		d['ID Email'] = identity['email']
		d['ID Phone'] = identity['phone']
		d['ID SSN'] = identity['ssn']
		d['ID Username'] = identity['username']
		d['ID Passport Number'] = identity['passportNumber']
		d['ID License Number'] = identity['licenseNumber']
		return d

	def format_login(login: dict) -> dict:
		d = {}
		d['Username'] = login['username']
		d['Password'] = login['password']
		d['TOTP'] = login['totp']

		uris = login.get('uris', [])
		if len(uris) == 1:
			d['URL'] = uris[0]['uri']
		else:
			for index, uri in enumerate(login.get('uris', [])):
				d['URL ' + str(index+1)] = uri['uri']
		return d

	def format(self) -> str:
		d = {}
		item = self.json
		item_type = self.item_type()

		# Name
		d['Name'] = item['name']

		# Add type specific fields
		if item_type == 'login':
			d.update(BWItem.format_login(item['login']))
		elif item_type == 'note':
			pass
		elif item_type == 'card':
			d.update(BWItem.format_card(item['card']))
		elif item_type == 'identity':
			d.update(BWItem.format_identity(item['identity']))

		# Add custom fields
		for index, field in enumerate(item.get('fields', [])):
			fieldname = '[Custom Field {}] {}'.format(index+1, field['name'])
			d[fieldname] = field['value']

		# Add attachment links
		for index, attachment in enumerate(item.get('attachments', [])):
			d['Attachment {} File Name'.format(index)] = attachment['fileName']
			d['Attachment {} File Size'.format(index)] = attachment['sizeName']
			d['Attachment {} URL'.format(index)] = attachment['url']

		d['Notes'] = item['notes']

		lines = '\n'.join(["{}: {}".format(k, v) for k,v in d.items() if not v is None])
		return lines + '\n'

class Cli:
	def run(command: [str], log_output = True) -> subprocess.CompletedProcess:
		if log_output: print('>', " ".join(command))
		return subprocess.run(command, stdout=subprocess.PIPE)

	def run_pipe(command: [str], input: str, log_output = True) -> subprocess.CompletedProcess:
		if log_output: print('>', " ".join(command))
		return subprocess.run(command, stdout=subprocess.PIPE, input=bytes(input, 'utf-8'))

class BWCli(Cli):
	def unlock(self) -> str:
		while True:
			process = Cli.run(['bw', 'unlock', '--raw'])
			session = process.stdout.decode('utf-8')
			if len(session) > 0:
				return session 

	def sync(self, session: str):
		Cli.run(['bw', '--session', session, 'sync'])

	def list_items(self, session: str) -> str:
		process = Cli.run(['bw', '--session', session, 'list', 'items'])
		return process.stdout.decode('utf-8')

class PassCli(Cli):

	def __init__(self):
		self.pass_directory = os.getenv('PASSWORD_STORE_DIR', default=os.path.join(Path.home(), '.password-store'))

	def get_file_path(self, name: str):
		return os.path.join(self.pass_directory, name + '.gpg')

	def insert(self, name: str, content: str) -> str: 
		process = Cli.run_pipe(['pass', 'insert', '-m', name], content, False)
		return process.stdout.decode('utf-8')

	def remove_force(self, name: str):
		os.remove(self.get_file_path(name))

	def pass_exists(self, name: str) -> bool:
		return os.path.exists(self.get_file_path(name))

	def list_pass_names(self):
		entries = os.scandir(self.pass_directory)
		return [n.name.removesuffix('.gpg') for n in entries if n.name.endswith('.gpg')]

def main(args):
	print('************************************************************')
	print('Note: To ensure a full refresh, logout and login again with:')
	print('\tbw logout')
	print('\tbw login')
	print('************************************************************')

	passcli = PassCli()
	bwcli = BWCli()

	print('Unlocking bitwarden')
	session = bwcli.unlock()
	print('Syncing bitwarden passwords')
	bwcli.sync(session)
	print('Listing bitwarden items')
	items = bwcli.list_items(session)

	existing_pass_entries = passcli.list_pass_names()
	bw_items = [BWItem(obj) for obj in json.loads(items)]

	for bw_item in bw_items:
		name = bw_item.passname()
		content = bw_item.format()

		if (passcli.pass_exists(name)):
			passcli.remove_force(name)
			print('Removed existing pass entry {}'.format(name))

		insert_response = passcli.insert(name, content)
		content_bytes = content.encode('utf8')
		print("Inserted {} bytes into {}".format(len(content_bytes), name))

	synced_pass_entries = [bw_item.passname() for bw_item in bw_items]
	ignored_pass_entries = [entry for entry in existing_pass_entries if not entry in synced_pass_entries]

	if len(ignored_pass_entries) > 0:
		print('WARNING: Ignored the following password entries. Possibly deleted from bitwarden?')
		for entry in ignored_pass_entries:
			print('\t{}'.format(entry))

main([]);
